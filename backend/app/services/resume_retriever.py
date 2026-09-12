# pyrefly: ignore [missing-import]
"""Resume RAG indexing + retrieval.

Builds on the existing sentence-transformer embedding path (semantic_matcher's
lazily-loaded All-MiniLM-L6-v2 model) and the resume chunker. Chunks are
persisted with 384-dim pgvector embeddings when a resume is uploaded; retrieval
uses a PostgreSQL `<=>` cosine-distance query to return the chunks most
relevant to a job description.

Graceful degradation (matching the rest of the AI services):
  - embedding model unavailable -> embedding stored as NULL, retrieval uses a
    deterministic normalized keyword-overlap scorer
  - chunks missing / DB error on the vector query -> same keyword fallback
  - nothing indexed  -> empty result, callers keep their pre-RAG behaviour
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple, Any

from sqlalchemy import select

from app.models import Resume, ResumeChunk, VECTOR_DIM
from app.services import resume_chunker, semantic_matcher
from app.services.resume_chunker import ResumeChunkData, chunk_resume_text
from app.services.resume_parser import _normalize

DEFAULT_TOP_K = 5
MAX_SOURCE_CHARS = 2000


@dataclass
class RetrievedChunk:
    """A ranked resume chunk returned by the retriever."""

    chunk_id: int
    chunk_index: int
    section: Optional[str]
    score: int
    content: str


# ---------------------------------------------------------------------------
# Embedding (thin wrapper over the shared semantic-matcher model)
# ---------------------------------------------------------------------------

def get_model():
    """Return the shared lazily-loaded SentenceTransformer (or None)."""
    return semantic_matcher.get_embedding_model()


def embed_texts(model: Any, texts: List[str]) -> Optional[List[List[float]]]:
    """Embed a list of texts; returns a (n, VECTOR_DIM) list or None on failure."""
    if model is None or not texts:
        return None
    try:
        vectors = model.encode(texts)
        return [list(map(float, v)) for v in vectors]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def build_chunk_rows(
    resume_id: int,
    chunk_data: List[ResumeChunkData],
    embeddings: Optional[List[List[float]]] = None,
) -> List[ResumeChunk]:
    """Construct (unsaved) ResumeChunk ORM objects from chunk data.

    Embeddings are optional: when the model was unavailable they stay NULL and
    retrieval falls back to keyword scoring for these chunks.
    """
    rows: List[ResumeChunk] = []
    for index, data in enumerate(chunk_data):
        embedding = None
        if embeddings is not None and index < len(embeddings):
            candidate = embeddings[index]
            if _valid_embedding(candidate):
                embedding = candidate
        rows.append(
            ResumeChunk(
                resume_id=resume_id,
                chunk_index=index,
                section=data.section,
                content=data.content,
                token_count=data.token_count,
                embedding=embedding,
            )
        )
    return rows


def _valid_embedding(vector: Optional[List[float]]) -> bool:
    if not vector or len(vector) != VECTOR_DIM:
        return False
    return any(v != 0 for v in vector)


def index_resume_chunks(
    db,
    resume: Resume,
    model: Any = None,
    chunker=chunk_resume_text,
) -> int:
    """Chunk a resume, embed it, and persist ResumeChunk rows.

    Existing chunks for the resume are replaced. Never raises: on any embedding
    failure the resume is indexed with NULL embeddings so upload still succeeds.
    Returns the number of chunks persisted.
    """
    text = (resume.parsed_text or "").strip()
    if not text:
        return 0
    if model is None:
        model = get_model()

    chunk_data = chunker(text)
    if not chunk_data:
        return 0

    embeddings = None
    if model is not None:
        embeddings = embed_texts(model, [c.content for c in chunk_data])

    rows = build_chunk_rows(resume.id, chunk_data, embeddings)

    db.query(ResumeChunk).filter(ResumeChunk.resume_id == resume.id).delete(
        synchronize_session=False
    )
    for row in rows:
        db.add(row)
    return len(rows)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _cosine_distance(a: List[float], b: List[float]) -> float:
    import numpy as np

    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    norm = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if norm == 0:
        return 1.0
    return 1.0 - float(np.dot(va, vb) / norm)


def _query_nearest(db, resume_id: int, query_vector: List[float], top_k: int):
    """pgvector nearest-neighbor query (cosine distance), null embeddings skipped."""
    stmt = (
        select(ResumeChunk)
        .where(
            ResumeChunk.resume_id == resume_id,
            ResumeChunk.embedding.is_not(None),
        )
        .order_by(ResumeChunk.embedding.cosine_distance(query_vector))
        .limit(top_k)
    )
    return list(db.scalars(stmt).all())


def keyword_retrieval(
    chunks: List[ResumeChunk],
    job_description: str,
    top_k: int = DEFAULT_TOP_K,
) -> List[RetrievedChunk]:
    """Deterministic keyword-overlap ranking used when embeddings are absent."""
    job_tokens = set(_tokens(job_description))
    if not job_tokens:
        return []
    scored: List[Tuple[int, ResumeChunk]] = []
    for chunk in chunks:
        chunk_tokens = _tokens(chunk.content)
        if not chunk_tokens:
            continue
        shared = len(job_tokens & chunk_tokens)
        # score = share of the job's meaningful tokens present in the chunk
        score = int(round((shared / len(job_tokens)) * 100))
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        _to_retrieved_chunk(chunk, score)
        for score, chunk in scored[:top_k]
    ]


def _tokens(text: str) -> set:
    norm = _normalize(text or "")
    return {t for t in norm.split(" ") if len(t) >= 2}


def _to_retrieved_chunk(chunk: ResumeChunk, score: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        section=chunk.section,
        score=max(0, min(100, score)),
        content=chunk.content,
    )


def retrieve_chunks_for_job(
    db,
    resume: Resume,
    job_description: Optional[str],
    top_k: int = DEFAULT_TOP_K,
    model: Any = None,
) -> Tuple[List[RetrievedChunk], str, bool]:
    """Return the resume chunks most relevant to a job description.

    Returns (chunks, model_used, used_fallback):
      - "all-MiniLM-L6-v2" when the pgvector path ran,
      - "fallback" when keyword scoring was used,
      - "none" when there was nothing to retrieve.
    Never raises; callers can pass `[]` onwards and keep pre-RAG behavior.
    """
    if not resume or not (job_description or "").strip() or top_k <= 0:
        return [], "none", False
    if model is None:
        model = get_model()

    chunks = (
        db.query(ResumeChunk)
        .filter(ResumeChunk.resume_id == resume.id)
        .order_by(ResumeChunk.chunk_index)
        .all()
    )
    if not chunks:
        return [], "none", False

    if model is not None:
        query_vector = embed_texts(model, [job_description])
        if query_vector:
            try:
                nearest = _query_nearest(db, resume.id, query_vector[0], top_k)
                if nearest:
                    results = [
                        _to_retrieved_chunk(
                            chunk,
                            int(round((1 - _cosine_distance(query_vector[0], chunk.embedding)) * 100)),
                        )
                        for chunk in nearest
                        if chunk.embedding is not None
                    ]
                    results = [r for r in results if r.score >= 0]
                    if results:
                        return results, semantic_matcher.DEFAULT_MODEL, False
            except Exception:
                pass

    return keyword_retrieval(chunks, job_description, top_k), "fallback", True


# ---------------------------------------------------------------------------
# Sources for the LLM pipeline
# ---------------------------------------------------------------------------

def build_source(chunk: RetrievedChunk) -> dict:
    """Serialize a retrieved chunk as a recommendation source reference."""
    return {
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "section": chunk.section,
        "score": chunk.score,
        "content": chunk.content[:MAX_SOURCE_CHARS],
    }
"""Unit tests for resume RAG indexing + retrieval (hermetic, no DB / model)."""
import hashlib
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models import Resume, ResumeChunk, VECTOR_DIM  # noqa: E402
from app.services import resume_retriever, semantic_matcher  # noqa: E402
from app.services.resume_chunker import ResumeChunkData  # noqa: E402
from app.services.resume_retriever import (  # noqa: E402
    build_chunk_rows,
    index_resume_chunks,
    keyword_retrieval,
    retrieve_chunks_for_job,
    _cosine_distance,
)

RESUME_TEXT = (
    "Python developer with Django, PostgreSQL and Docker experience. "
    "Built REST APIs on AWS and deployed microservices."
)
JOB_DESC = "Looking for a Python Django backend engineer with AWS and Docker."
CHUNK_DATA = [
    ResumeChunkData(section="experience", content="Python Django PostgreSQL AWS", token_count=4),
    ResumeChunkData(section="skills", content="Docker Kubernetes", token_count=2),
]


def _fake_vector(text: str) -> list:
    vec = [0.0] * VECTOR_DIM
    for token in text.lower().split():
        idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % VECTOR_DIM
        vec[idx] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


class FakeModel:
    """Deterministic 384-dim stand-in for the SentenceTransformer."""

    def encode(self, texts):
        return [_fake_vector(t) for t in texts]


class FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._result

    def first(self):
        return self._result[0] if self._result else None

    def delete(self, **k):
        return 0


class FakeScalars:
    def __init__(self, result):
        self._result = result

    def all(self):
        return self._result


class FakeDB:
    """Stands in for the SQLAlchemy session in retrieval tests."""

    def __init__(self, query_result, scalars_result=None):
        self._query_result = query_result
        self._scalars_result = scalars_result

    def query(self, model):
        return FakeQuery(self._query_result)

    def scalars(self, stmt):
        return FakeScalars(self._scalars_result)


class IndexDB:
    """Stands in for the session during indexing."""

    def __init__(self):
        self.added = []
        self.deleted = False

    def query(self, model):
        return FakeQuery([])

    def add(self, row):
        self.added.append(row)


def _chunk(id_, index, content, section="skills", embedding=None):
    return ResumeChunk(
        id=id_,
        resume_id=1,
        chunk_index=index,
        section=section,
        content=content,
        token_count=len(content.split()),
        embedding=embedding,
    )


@pytest.fixture
def no_model(monkeypatch):
    """Force embedding-model unavailability for fallback tests."""
    monkeypatch.setattr(semantic_matcher, "_model", None)
    monkeypatch.setattr(semantic_matcher, "get_embedding_model", lambda *a, **k: None)


ALL_CHUNKS = [
    _chunk(1, 0, "Python Django PostgreSQL AWS developer", "experience", _fake_vector("Python Django PostgreSQL AWS developer")),
    _chunk(2, 1, "Expt with FastAPI, Docker, Kubernetes", "skills", _fake_vector("Expt with FastAPI, Docker, Kubernetes")),
    _chunk(3, 2, "Graphic design portfolio work in Figma", "design", _fake_vector("Graphic design portfolio work in Figma")),
]


# ---------------------------------------------------------------------------
# Embedding storage / chunk rows
# ---------------------------------------------------------------------------

def test_build_chunk_rows_embeddings_dim_and_order():
    embeddings = [_fake_vector(c.content) for c in CHUNK_DATA]
    rows = build_chunk_rows(resume_id=99, chunk_data=CHUNK_DATA, embeddings=embeddings)
    assert len(rows) == 2
    for i, row in enumerate(rows):
        assert row.resume_id == 99
        assert row.chunk_index == i
        assert row.section == CHUNK_DATA[i].section
        assert row.content == CHUNK_DATA[i].content
        assert row.token_count == CHUNK_DATA[i].token_count
        assert len(row.embedding) == VECTOR_DIM


def test_build_chunk_rows_no_embeddings_stores_null():
    rows = build_chunk_rows(resume_id=1, chunk_data=CHUNK_DATA, embeddings=None)
    assert all(row.embedding is None for row in rows)


def test_build_chunk_rows_rejects_wrong_dim_embedding():
    rows = build_chunk_rows(
        resume_id=1, chunk_data=CHUNK_DATA[:1], embeddings=[[0.1] * (VECTOR_DIM - 2)]
    )
    assert rows[0].embedding is None


def test_index_resume_chunks_persists_rows_with_embeddings():
    resume = Resume(id=7, parsed_text=RESUME_TEXT)
    db = IndexDB()
    count = index_resume_chunks(db, resume, model=FakeModel())
    assert count == len(db.added) >= 1
    assert all(len(r.embedding) == VECTOR_DIM for r in db.added)
    assert all(r.resume_id == 7 for r in db.added)
    assert [r.chunk_index for r in db.added] == list(range(len(db.added)))


def test_index_resume_chunks_without_model_stores_null(no_model):
    resume = Resume(id=7, parsed_text=RESUME_TEXT)
    db = IndexDB()
    count = index_resume_chunks(db, resume, model=None)
    assert count > 0
    assert all(r.embedding is None for r in db.added)


def test_index_empty_resume_persists_nothing():
    db = IndexDB()
    assert index_resume_chunks(db, Resume(id=1, parsed_text="  "), model=FakeModel()) == 0
    assert db.added == []


# ---------------------------------------------------------------------------
# Retrieval: pgvector path
# ---------------------------------------------------------------------------

def test_retrieval_uses_vector_path_and_returns_ranked_chunks():
    nearest = [ALL_CHUNKS[2], ALL_CHUNKS[0]]  # whatever the DB "distance" ordered
    db = FakeDB(query_result=ALL_CHUNKS, scalars_result=nearest)
    resume = Resume(id=1, parsed_text="x")

    chunks, model_used, used_fallback = retrieve_chunks_for_job(
        db, resume, JOB_DESC, top_k=2, model=FakeModel()
    )

    assert model_used == semantic_matcher.DEFAULT_MODEL
    assert used_fallback is False
    # DB order is preserved, embeddings carried, scores bounded.
    assert [c.chunk_id for c in chunks] == [3, 1]
    assert all(0 <= c.score <= 100 for c in chunks)
    assert chunks[0].section == "design" and chunks[0].content.startswith("Graphic")


def test_retrieval_score_matches_cosine_100_percent_same_vector():
    v = _fake_vector("python django aws docker")
    nearest = [_chunk(1, 0, "python django aws docker", embedding=v)]
    db = FakeDB(query_result=nearest, scalars_result=nearest)
    chunks, _, _ = retrieve_chunks_for_job(
        db, Resume(id=1, parsed_text="x"), "python django aws docker",
        top_k=1, model=FakeModel(),
    )
    assert chunks[0].score >= 99  # identical embedding -> cosine 1 -> score ~100


# ---------------------------------------------------------------------------
# Retrieval: keyword fallback
# ---------------------------------------------------------------------------

def test_retrieval_falls_back_to_keywords_without_model(no_model):
    db = FakeDB(query_result=ALL_CHUNKS)
    chunks, model_used, used_fallback = retrieve_chunks_for_job(
        db, Resume(id=1, parsed_text="x"), JOB_DESC
    )
    assert model_used == "fallback"
    assert used_fallback is True
    assert len(chunks) > 0
    # Most keyword-overlapping chunk (Python/Django/AWS) ranks first.
    assert chunks[0].chunk_id == 1


def test_keyword_retrieval_returns_top_k_sorted():
    result = keyword_retrieval(ALL_CHUNKS, JOB_DESC, top_k=2)
    assert len(result) == 2
    scores = [c.score for c in result]
    assert scores == sorted(scores, reverse=True)


def test_keyword_retrieval_empty_job_returns_nothing():
    assert keyword_retrieval(ALL_CHUNKS, "  ") == []


def test_empty_or_missing_resume_returns_none():
    chunks, model_used, _ = retrieve_chunks_for_job(
        FakeDB(query_result=ALL_CHUNKS), None, JOB_DESC, model=FakeModel()
    )
    assert chunks == [] and model_used == "none"

    db = FakeDB(query_result=[])
    chunks, model_used, _ = retrieve_chunks_for_job(
        db, Resume(id=1, parsed_text="x"), None
    )
    assert chunks == [] and model_used == "none"


def test_retrieval_with_no_chunks_returns_none():
    db = FakeDB(query_result=[])
    chunks, model_used, _ = retrieve_chunks_for_job(
        db, Resume(id=1, parsed_text="x"), JOB_DESC, model=FakeModel()
    )
    assert chunks == [] and model_used == "none"


# ---------------------------------------------------------------------------
# Distance helper
# ---------------------------------------------------------------------------

def test_cosine_distance_zero_for_identical():
    v = _fake_vector("python django")
    assert _cosine_distance(v, v) == pytest.approx(0.0, abs=1e-6)


def test_cosine_distance_one_for_orthogonal():
    a = [1.0] + [0.0] * (VECTOR_DIM - 1)
    b = [0.0] + [1.0] + [0.0] * (VECTOR_DIM - 2)
    assert _cosine_distance(a, b) == pytest.approx(1.0)
# pyrefly: ignore [missing-import]
"""Resume text chunking.

Splits the parsed resume text into meaningful chunks so they can be embedded
and stored in the pgvector index. Chunking is section-aware: common resume
headings (Experience, Projects, Skills, Education, ...) become boundaries, and
long sections are further split into overlapping token windows. Pure rule-based
logic (no LLM), reusing no external services.
"""
import re
from dataclasses import dataclass
from typing import List, Tuple

# Window sizes (approximate whitespace-token counts, not subword tokens).
DEFAULT_MAX_TOKENS = 400
DEFAULT_OVERLAP_TOKENS = 60
DEFAULT_MIN_CHUNK_TOKENS = 120

# Resume headings that begin a new section when found on their own line.
SECTION_HEADINGS = [
    "contact",
    "personal information",
    "summary",
    "professional summary",
    "objective",
    "profile",
    "experience",
    "work experience",
    "professional experience",
    "employment history",
    "project experience",
    "projects",
    "personal projects",
    "academic projects",
    "education",
    "skills",
    "technical skills",
    "core competencies",
    "certifications",
    "certificates",
    "professional certifications",
    "achievements",
    "accomplishments",
    "awards",
    "honors",
    "publications",
    "languages",
    "volunteer",
    "volunteer experience",
    "leadership",
    "extracurricular",
    "interests",
    "hobbies",
    "references",
    "additional information",
    "training",
]

# "Technical Skills" -> "technicall skills" -> "technicallskills", tolerant to
# punctuation/whitespace variants on the heading line.
_HEADING_NORMS = {re.sub(r"[^a-z0-9]+", "", h) for h in SECTION_HEADINGS}


@dataclass
class ResumeChunkData:
    """One raw (un-embedded) chunk of a resume."""

    section: str
    content: str
    token_count: int


def _heading_norm(line: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", line.lower())


def _is_heading(line: str) -> bool:
    return _heading_norm(line) in _HEADING_NORMS


def _label_for(line: str) -> str:
    label = _heading_norm(line)
    # Keep the canonical heading spelling where available, otherwise the
    # normalized line itself.
    for heading in SECTION_HEADINGS:
        if re.sub(r"[^a-z0-9]+", "", heading) == label:
            return heading
    return label[:40]


def split_resume_sections(text: str) -> List[Tuple[str, str]]:
    """Split resume text into (section_label, section_text) pairs.

    A line that looks like a known resume heading becomes a boundary. Sections
    without a heading are grouped under "general". Empty sections are dropped.
    """
    if not text or not text.strip():
        return []
    sections: List[Tuple[str, str]] = []
    current_header = "general"
    current_buf: List[str] = []

    for line in text.splitlines():
        if _is_heading(line):
            if current_buf:
                sections.append((current_header, "\n".join(current_buf).strip()))
                current_buf = []
            current_header = _label_for(line)
        else:
            if line.strip():
                current_buf.append(line)

    if current_buf:
        sections.append((current_header, "\n".join(current_buf).strip()))

    return [(label, content) for label, content in sections if content]


def _window_text(tokens: List[str], max_tokens: int, overlap: int, min_chunk: int) -> List[str]:
    if not tokens:
        return []
    if len(tokens) <= max_tokens:
        return [" ".join(tokens)]
    step = max(1, max_tokens - overlap)
    parts: List[str] = []
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + max_tokens)
        parts.append(" ".join(tokens[start:end]))
        if end == len(tokens):
            break
        start += step
    # Merge a trailing undersized window into the previous one.
    while len(parts) > 1 and len(parts[-1].split()) < min_chunk:
        parts[-2] = f"{parts[-2]} {parts.pop()}"
    return parts


def chunk_text(
    text: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    min_chunk_tokens: int = DEFAULT_MIN_CHUNK_TOKENS,
) -> List[str]:
    """Private token-window chunking of a single block of text."""
    tokens = (text or "").split()
    return _window_text(tokens, max_tokens, overlap_tokens, min_chunk_tokens)


def chunk_resume_text(
    text: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    min_chunk_tokens: int = DEFAULT_MIN_CHUNK_TOKENS,
) -> List[ResumeChunkData]:
    """Chunk parsed resume text into ordered, section-aware chunks.

    Returns an empty list for empty/whitespace input. `chunk_index` is assigned
    sequentially across all sections by the caller (or when persisting).
    """
    sections = split_resume_sections(text)
    chunks: List[ResumeChunkData] = []
    for label, content in sections:
        for window in _window_text(
            content.split(), max_tokens, overlap_tokens, min_chunk_tokens
        ):
            if window.strip():
                chunks.append(
                    ResumeChunkData(
                        section=label,
                        content=window.strip(),
                        token_count=len(window.split()),
                    )
                )
    # Entirely header-less resumes still produce one "general" chunk.
    if not chunks and (text or "").strip():
        chunks.append(
            ResumeChunkData(
                section="general",
                content=" ".join((text or "").split()),
                token_count=len((text or "").split()),
            )
        )
    return chunks
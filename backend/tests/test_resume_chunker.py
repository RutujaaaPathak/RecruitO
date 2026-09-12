"""Unit tests for the section-aware resume chunker."""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.resume_chunker import (  # noqa: E402
    ResumeChunkData,
    chunk_resume_text,
    split_resume_sections,
)


SAMPLE_RESUME = """John Doe
john@example.com

SUMMARY
Backend engineer with 5 years of Python and Django experience.

EXPERIENCE
Senior Engineer at Acme (2020-2024): built REST APIs with Django and
PostgreSQL, deployed with Docker on AWS.

EDUCATION
B.Tech Computer Science, 2019.

SKILLS
Python, Django, PostgreSQL, Docker, AWS
"""


def test_splits_into_sections():
    sections = split_resume_sections(SAMPLE_RESUME)
    labels = [label for label, _ in sections]
    assert "summary" in labels
    assert "experience" in labels
    assert "education" in labels
    assert "skills" in labels


def test_section_content_is_preserved():
    sections = dict(split_resume_sections(SAMPLE_RESUME))
    assert "Senior Engineer" in sections["experience"]
    assert "Python, Django, PostgreSQL, Docker, AWS" in sections["skills"]


def test_no_heading_uses_general():
    text = "Just a block of resume text without any headings whatsoever."
    chunks = chunk_resume_text(text)
    assert len(chunks) == 1
    assert chunks[0].section == "general"


def test_empty_text_returns_no_chunks():
    assert chunk_resume_text("") == []
    assert chunk_resume_text("   \n  ") == []


def test_long_section_is_windowed_with_overlap():
    tokens = [f"word{i}" for i in range(2000)]
    text = " ".join(tokens)
    chunks = chunk_resume_text(text, max_tokens=400, overlap_tokens=60, min_chunk_tokens=120)
    assert len(chunks) > 1
    # ordered, contiguous-with-overlap
    assert chunks[0].token_count <= 400
    first_end = " ".join(chunks[0].content.split()).rsplit(" word", 1)[0]
    assert chunks[1].content.startswith("word")
    # overlap exists between neighbours
    c0 = set(chunks[0].content.split())
    c1 = set(chunks[1].content.split())
    assert c0 & c1


def test_trailing_undersized_chunk_is_merged():
    tokens = [f"word{i}" for i in range(990)]
    text = " ".join(tokens)
    chunks = chunk_resume_text(text, max_tokens=400, overlap_tokens=60, min_chunk_tokens=120)
    last = chunks[-1]
    assert last.token_count >= 120  # merged, not a stub


def test_chunk_objects_have_index_fields_ready():
    chunks = chunk_resume_text(SAMPLE_RESUME)
    assert all(isinstance(c, ResumeChunkData) for c in chunks)
    assert all(c.token_count == len(c.content.split()) for c in chunks)
    assert all(c.section for c in chunks)
    assert all(c.content for c in chunks)
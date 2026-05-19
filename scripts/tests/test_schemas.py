import pytest
from signal_brain.wiki.schemas import (
    parse_page, render_page, validate_page,
    REQUIRED_SECTIONS, SchemaError,
)


def test_parse_page_extracts_frontmatter_and_body():
    text = """---
type: person
slug: alice
---

## Background
Hello.
"""
    fm, body = parse_page(text)
    assert fm["type"] == "person"
    assert fm["slug"] == "alice"
    assert "## Background" in body


def test_render_page_roundtrip():
    fm = {"type": "person", "slug": "alice", "name": "Alice Example"}
    body = "## Background\nHello."
    text = render_page(fm, body)
    fm2, body2 = parse_page(text)
    assert fm2 == fm
    assert body2.strip() == body.strip()


def test_validate_position_page_requires_sections():
    fm = {"type": "position", "holder": "alice", "concept": "topic-a-policy",
          "stance": "x", "confidence": "high", "first_seen": "[B0001#m1]",
          "last_seen": "[B0001#m1]", "evolution": "stable", "sources_count": 1}
    body = "## Core claim\nx"  # missing other required sections
    with pytest.raises(SchemaError) as e:
        validate_page("position", fm, body)
    assert "Reasoning chain" in str(e.value) or "missing section" in str(e.value).lower()


def test_validate_position_page_passes_with_all_sections():
    fm = {"type": "position", "holder": "alice", "concept": "topic-a-policy",
          "stance": "x", "confidence": "high", "first_seen": "[B0001#m1]",
          "last_seen": "[B0001#m1]", "evolution": "stable", "sources_count": 1}
    body = "\n".join(f"## {s}\nbody" for s in REQUIRED_SECTIONS["position"])
    validate_page("position", fm, body)


def test_required_sections_cover_all_page_types():
    for t in ["person", "concept", "position", "arc", "cross"]:
        assert t in REQUIRED_SECTIONS
        assert len(REQUIRED_SECTIONS[t]) >= 3


def test_parse_page_tolerates_trailing_whitespace_on_closing_delimiter():
    text = "---\ntype: person\nslug: alice\n---  \n\n## Background\nHello.\n"
    fm, body = parse_page(text)
    assert fm["slug"] == "alice"
    assert "## Background" in body

"""Tests for the wiki page plan/render API.

Each generator splits into build_*_prompts (returns the tuple needed to emit a
synthesis todo) and render_*_page (validates and renders with the planned
frontmatter once the agent has supplied a body).
"""
from signal_brain.wiki.concepts import build_concept_prompts, render_concept_page
from signal_brain.wiki.positions import build_position_prompts, render_position_page
from signal_brain.wiki.arcs import build_arc_prompts, render_arc_page
from signal_brain.wiki.cross import build_cross_prompts, render_cross_page
from signal_brain.wiki.schemas import parse_page, validate_page


CONCEPT_BODY = """## What's at stake
Issue.

## Sub-questions
Sub.

## Empirical anchors
Anchors [B0001#m1].

## Positions on this concept
- [[positions/alice--topic-a-policy]]

## Related
(auto-maintained — see link pass)
"""


POSITION_BODY = """## Core claim
Claim.

## Reasoning chain
Chain [B0001#m2].

## Examples / evidence cited
Examples.

## Concessions made
Concessions.

## Tensions with own other positions
Tensions.

## Evolution timeline
Timeline.

## Counter-arguments faced
Counters.

## Related
(auto-maintained — see link pass)
"""


ARC_BODY = """## Question at stake
Question.

## Opening positions
Positions.

## Key turns
- [B0042#m17]: turn.

## Concessions & ground gained
None.

## Why unresolved
Reasons.

## Related
(auto-maintained — see link pass)
"""


CROSS_BODY = """## Overview
Pattern overview.

## Instances
- [B0042#m17]: instance.

## Related
(auto-maintained — see link pass)
"""


def test_build_concept_prompts_returns_tuple_and_fm():
    system, user, schema, fm = build_concept_prompts(
        slug="topic-a-policy", aliases=["alt-name"],
        contested=True, sources_count=87, bursts_summary="...",
    )
    assert "concept" in system.lower()
    assert "topic-a-policy" in user
    assert schema == {"required": ["body"], "types": {"body": "str"}}
    assert fm["type"] == "concept"
    assert fm["slug"] == "topic-a-policy"
    assert fm["aliases"] == ["alt-name"]
    assert fm["contested"] is True
    assert fm["sources_count"] == 87


def test_render_concept_page_validates():
    _, _, _, fm = build_concept_prompts(
        slug="topic-a-policy", aliases=["alt-name"],
        contested=True, sources_count=87, bursts_summary="...",
    )
    page = render_concept_page(fm, CONCEPT_BODY)
    parsed_fm, body = parse_page(page)
    assert parsed_fm["type"] == "concept"
    validate_page("concept", parsed_fm, body)


def test_build_position_prompts_returns_tuple_and_fm():
    system, user, schema, fm = build_position_prompts(
        holder="alice", concept="topic-a-policy",
        stance="Concentration > threshold should be structurally prevented.",
        confidence="high",
        first_seen="[B0014#m3]", last_seen="[B0186#m22]",
        evolution="stable", sources_count=34,
        bursts_summary="...", counterpart_summary="...",
    )
    assert "position" in system.lower()
    assert "alice" in user
    assert schema == {"required": ["body"], "types": {"body": "str"}}
    assert fm["type"] == "position"
    assert fm["holder"] == "alice"
    assert fm["concept"] == "topic-a-policy"


def test_render_position_page_validates():
    _, _, _, fm = build_position_prompts(
        holder="alice", concept="topic-a-policy",
        stance="Concentration > threshold should be structurally prevented.",
        confidence="high",
        first_seen="[B0014#m3]", last_seen="[B0186#m22]",
        evolution="stable", sources_count=34,
        bursts_summary="...", counterpart_summary="...",
    )
    page = render_position_page(fm, POSITION_BODY)
    parsed_fm, body = parse_page(page)
    assert parsed_fm["type"] == "position"
    assert parsed_fm["holder"] == "alice"
    validate_page("position", parsed_fm, body)


def test_build_arc_prompts_returns_tuple_and_fm():
    system, user, schema, fm = build_arc_prompts(
        arc_id="A007", slug="topic-a-debate",
        period=["2026-05-04", "2026-05-19"],
        bursts=["B0038", "B0039"], primary_topic="topic-a",
        bursts_summary="...",
    )
    assert schema == {"required": ["body"], "types": {"body": "str"}}
    assert fm["type"] == "arc"
    assert fm["id"] == "A007"
    assert fm["slug"] == "topic-a-debate"
    assert fm["bursts"] == ["B0038", "B0039"]


def test_render_arc_page_validates():
    _, _, _, fm = build_arc_prompts(
        arc_id="A007", slug="topic-a-debate",
        period=["2026-05-04", "2026-05-19"],
        bursts=["B0038", "B0039"], primary_topic="topic-a",
        bursts_summary="...",
    )
    page = render_arc_page(fm, ARC_BODY)
    parsed_fm, body = parse_page(page)
    assert parsed_fm["type"] == "arc"
    assert parsed_fm["id"] == "A007"
    validate_page("arc", parsed_fm, body)


def test_build_cross_prompts_returns_tuple_and_fm():
    system, user, schema, fm = build_cross_prompts(
        slug="disagreements", title="Disagreements", instances_summary="...",
    )
    assert schema == {"required": ["body"], "types": {"body": "str"}}
    assert fm["type"] == "cross"
    assert fm["slug"] == "disagreements"
    assert fm["title"] == "Disagreements"


def test_render_cross_page_validates():
    _, _, _, fm = build_cross_prompts(
        slug="disagreements", title="Disagreements", instances_summary="...",
    )
    page = render_cross_page(fm, CROSS_BODY)
    parsed_fm, body = parse_page(page)
    assert parsed_fm["type"] == "cross"
    validate_page("cross", parsed_fm, body)

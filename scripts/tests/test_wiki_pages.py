from signal_brain.wiki.concepts import generate_concept_page
from signal_brain.wiki.positions import generate_position_page
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


def test_generate_concept_page_validates(mocker):
    llm = mocker.MagicMock()
    llm.complete.return_value.text = CONCEPT_BODY
    page = generate_concept_page(
        slug="topic-a-policy", aliases=["alt-name"],
        contested=True, sources_count=87, bursts_summary="...", llm=llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "concept"
    validate_page("concept", fm, body)


def test_generate_position_page_validates(mocker):
    llm = mocker.MagicMock()
    llm.complete.return_value.text = POSITION_BODY
    page = generate_position_page(
        holder="alice", concept="topic-a-policy",
        stance="Concentration > threshold should be structurally prevented.",
        confidence="high",
        first_seen="[B0014#m3]", last_seen="[B0186#m22]",
        evolution="stable", sources_count=34,
        bursts_summary="...", counterpart_summary="...", llm=llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "position"
    assert fm["holder"] == "alice"
    assert fm["concept"] == "topic-a-policy"
    validate_page("position", fm, body)


from signal_brain.wiki.arcs import generate_arc_page
from signal_brain.wiki.cross import generate_cross_page


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


def test_generate_arc_page_validates(mocker):
    llm = mocker.MagicMock()
    llm.complete.return_value.text = ARC_BODY
    page = generate_arc_page(
        arc_id="A007", slug="topic-a-debate",
        period=["2026-05-04", "2026-05-19"],
        bursts=["B0038", "B0039"], primary_topic="topic-a",
        bursts_summary="...", llm=llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "arc"
    assert fm["id"] == "A007"
    validate_page("arc", fm, body)


def test_generate_cross_page_validates(mocker):
    llm = mocker.MagicMock()
    llm.complete.return_value.text = CROSS_BODY
    page = generate_cross_page(
        slug="disagreements", title="Disagreements",
        instances_summary="...", llm=llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "cross"
    validate_page("cross", fm, body)

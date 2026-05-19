from signal_brain.wiki.people import build_person_prompts, render_person_page
from signal_brain.wiki.schemas import parse_page, validate_page


PERSON_BODY = """## Background
Some background about Alice with a citation [B0001#m1].

## Style & drivers
Drives.

## Key positions
- [[positions/alice--topic-a-policy]]

## Recurring moves
Moves.

## Open tensions
Tensions.

## Related
(auto-maintained)
"""


def test_build_person_prompts_returns_tuple_and_fm():
    system, user, schema, fm = build_person_prompts(
        slug="alice", name="Alice Example", relation="Me",
        bursts_summary="Bursts featuring Alice dominantly.",
        sources_count=1138,
    )
    assert "person" in system.lower()
    assert "Alice Example" in user
    assert schema == {"required": ["body"], "types": {"body": "str"}}
    assert fm["type"] == "person"
    assert fm["slug"] == "alice"
    assert fm["name"] == "Alice Example"
    assert fm["relation"] == "Me"
    assert fm["sources_count"] == 1138


def test_render_person_page_validates():
    _, _, _, fm = build_person_prompts(
        slug="alice", name="Alice Example", relation="Me",
        bursts_summary="Bursts featuring Alice dominantly.",
        sources_count=1138,
    )
    page = render_person_page(fm, PERSON_BODY)
    parsed_fm, body = parse_page(page)
    assert parsed_fm["type"] == "person"
    assert parsed_fm["slug"] == "alice"
    validate_page("person", parsed_fm, body)

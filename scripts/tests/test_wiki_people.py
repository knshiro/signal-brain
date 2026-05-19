from signal_brain.wiki.people import generate_person_page
from signal_brain.wiki.schemas import parse_page, validate_page


def test_generate_person_page_passes_schema(tmp_wiki_dir, mocker):
    mock_llm = mocker.MagicMock()
    mock_llm.complete.return_value.text = """## Background
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
    page = generate_person_page(
        slug="alice", name="Alice Example", relation="Me",
        bursts_summary="Bursts featuring Alice dominantly.",
        sources_count=1138, llm=mock_llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "person"
    assert fm["slug"] == "alice"
    validate_page("person", fm, body)

from signal_brain.linking import (
    build_deterministic_graph, write_related_blocks, run_stage1, run_stage2,
)
from signal_brain.wiki.schemas import render_page, parse_page


def _seed(tmp_wiki_dir):
    (tmp_wiki_dir / "people" / "alice.md").write_text(render_page(
        {"type": "person", "slug": "alice", "name": "Alice Example"},
        "## Background\nx\n## Style & drivers\nx\n## Key positions\nx\n## Recurring moves\nx\n## Open tensions\nx\n## Related\n(auto-maintained — see link pass)\n"), encoding="utf-8")
    (tmp_wiki_dir / "concepts" / "topic-a.md").write_text(render_page(
        {"type": "concept", "slug": "topic-a", "contested": True},
        "## What's at stake\nx\n## Sub-questions\nx\n## Empirical anchors\nx\n## Positions on this concept\nx\n## Related\n(auto-maintained — see link pass)\n"), encoding="utf-8")
    (tmp_wiki_dir / "positions" / "alice--topic-a.md").write_text(render_page(
        {"type": "position", "holder": "alice", "concept": "topic-a",
         "stance": "x", "confidence": "high", "first_seen": "[B0001#m1]",
         "last_seen": "[B0001#m1]", "evolution": "stable", "sources_count": 1},
        "## Core claim\nx\n## Reasoning chain\nx\n## Examples / evidence cited\nx\n## Concessions made\nx\n## Tensions with own other positions\nx\n## Evolution timeline\nx\n## Counter-arguments faced\nx\n## Related\n(auto-maintained — see link pass)\n"), encoding="utf-8")


def test_stage1_links_position_to_concept_and_person(tmp_wiki_dir):
    _seed(tmp_wiki_dir)
    run_stage1(tmp_wiki_dir)
    pos = (tmp_wiki_dir / "positions" / "alice--topic-a.md").read_text(encoding="utf-8")
    assert "[[concepts/topic-a]]" in pos
    assert "[[people/alice]]" in pos
    concept = (tmp_wiki_dir / "concepts" / "topic-a.md").read_text(encoding="utf-8")
    assert "[[positions/alice--topic-a]]" in concept
    person = (tmp_wiki_dir / "people" / "alice.md").read_text(encoding="utf-8")
    assert "[[positions/alice--topic-a]]" in person


def test_stage2_calls_llm_per_page(tmp_wiki_dir, mocker):
    _seed(tmp_wiki_dir)
    run_stage1(tmp_wiki_dir)
    llm = mocker.MagicMock()
    llm.complete_json.return_value = {"links": []}
    data_dir = tmp_wiki_dir.parent / "data"
    data_dir.mkdir(exist_ok=True)
    run_stage2(tmp_wiki_dir, llm, data_dir=data_dir)
    assert llm.complete_json.call_count == 3  # one per page


def test_write_related_block_is_idempotent(tmp_wiki_dir):
    _seed(tmp_wiki_dir)
    page = tmp_wiki_dir / "positions" / "alice--topic-a.md"
    write_related_blocks({page: ["[[concepts/topic-a]]", "[[people/alice]]"]})
    write_related_blocks({page: ["[[concepts/topic-a]]", "[[people/alice]]"]})
    body = page.read_text(encoding="utf-8")
    assert body.count("[[concepts/topic-a]]") == 1

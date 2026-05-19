import json
from signal_brain.lint import run_lint
from signal_brain.wiki.schemas import render_page


def test_unresolved_citations_flagged(tmp_path, tmp_wiki_dir):
    data = tmp_path / "data"
    data.mkdir()
    # Empty bursts/msgs so any citation is unresolved
    (data / "bursts.jsonl").write_text("", encoding="utf-8")
    (data / "msg_index.jsonl").write_text("", encoding="utf-8")
    (tmp_wiki_dir / "people" / "alice.md").write_text(render_page(
        {"type": "person", "slug": "alice", "name": "Alice Example"},
        "## Background\ncites [B0001#m1].\n## Style & drivers\nx\n## Key positions\nx\n## Recurring moves\nx\n## Open tensions\nx\n## Related\nx"), encoding="utf-8")
    report = tmp_wiki_dir / "lint-report.md"
    run_lint(tmp_wiki_dir, data, report)
    text = report.read_text(encoding="utf-8")
    assert "Unresolved citations" in text
    assert "[B0001#m1]" in text


def test_orphan_pages_flagged(tmp_path, tmp_wiki_dir):
    data = tmp_path / "data"
    data.mkdir()
    (data / "bursts.jsonl").write_text("", encoding="utf-8")
    (data / "msg_index.jsonl").write_text("", encoding="utf-8")
    (tmp_wiki_dir / "people" / "alice.md").write_text(render_page(
        {"type": "person", "slug": "alice", "name": "Alice Example"},
        "## Background\nx\n## Style & drivers\nx\n## Key positions\nx\n## Recurring moves\nx\n## Open tensions\nx\n## Related\n(empty)"), encoding="utf-8")
    report = tmp_wiki_dir / "lint-report.md"
    run_lint(tmp_wiki_dir, data, report)
    assert "Orphan" in report.read_text(encoding="utf-8")

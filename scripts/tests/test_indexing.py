from signal_brain.indexing import build_index, bootstrap_brain_root, append_log
from signal_brain.wiki.schemas import render_page


def test_build_index_lists_every_page(tmp_wiki_dir):
    (tmp_wiki_dir / "people" / "alice.md").write_text(render_page(
        {"type": "person", "slug": "alice", "name": "Alice Example", "sources_count": 5,
         "last_touched": "2026-05-19"},
        "## Background\nx\n## Style & drivers\nx\n## Key positions\nx\n## Recurring moves\nx\n## Open tensions\nx\n## Related\nx"), encoding="utf-8")
    (tmp_wiki_dir / "concepts" / "topic-a.md").write_text(render_page(
        {"type": "concept", "slug": "topic-a", "contested": True,
         "sources_count": 10, "last_touched": "2026-05-19"},
        "## What's at stake\nx\n## Sub-questions\nx\n## Empirical anchors\nx\n## Positions on this concept\nx\n## Related\nx"), encoding="utf-8")
    out = tmp_wiki_dir / "index.md"
    build_index(tmp_wiki_dir, out)
    text = out.read_text(encoding="utf-8")
    assert "## People" in text
    assert "[[people/alice]]" in text
    assert "## Concepts" in text
    assert "[[concepts/topic-a]]" in text


def test_bootstrap_brain_root_writes_two_files(tmp_path):
    bootstrap_brain_root(tmp_path)
    for name in ("AGENTS.md", "CLAUDE.md"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "Citation format" in text
        assert "[Bnnnn#mN]" in text
        assert "English" in text


def test_bootstrap_brain_root_is_idempotent(tmp_path):
    """User-edited files must not be overwritten on subsequent runs."""
    bootstrap_brain_root(tmp_path)
    (tmp_path / "AGENTS.md").write_text("custom user edit", encoding="utf-8")
    bootstrap_brain_root(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "custom user edit"


def test_append_log_is_append_only(tmp_wiki_dir):
    log = tmp_wiki_dir / "log.md"
    append_log(log, "## [2026-05-19] ingest | +1")
    append_log(log, "## [2026-05-19] lint | ok")
    text = log.read_text(encoding="utf-8")
    assert text.count("## [2026-05-19]") == 2
    assert text.index("ingest") < text.index("lint")

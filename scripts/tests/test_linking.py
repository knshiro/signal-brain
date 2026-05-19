"""Tests for the linking pass.

Stage 1 (deterministic) tests are unchanged from pre-refactor: same fixtures,
same assertions. Stage 2 is now plan/finalize — todos are emitted to a JSONL,
the agent writes done rows, and finalize merges/filters/persists.
"""
import json

from signal_brain.linking import (
    build_deterministic_graph,
    run_stage1,
    run_stage2_finalize,
    run_stage2_plan,
    write_related_blocks,
)
from signal_brain.wiki.schemas import render_page
from signal_brain.worklist import stable_job_id, load_todo


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


def test_write_related_block_is_idempotent(tmp_wiki_dir):
    _seed(tmp_wiki_dir)
    page = tmp_wiki_dir / "positions" / "alice--topic-a.md"
    write_related_blocks({page: ["[[concepts/topic-a]]", "[[people/alice]]"]})
    write_related_blocks({page: ["[[concepts/topic-a]]", "[[people/alice]]"]})
    body = page.read_text(encoding="utf-8")
    assert body.count("[[concepts/topic-a]]") == 1


def test_build_deterministic_graph_includes_all_seeded_pages(tmp_wiki_dir):
    _seed(tmp_wiki_dir)
    graph = build_deterministic_graph(tmp_wiki_dir)
    paths = {p.name for p in graph}
    assert "alice.md" in paths
    assert "topic-a.md" in paths
    assert "alice--topic-a.md" in paths


def test_stage2_plan_emits_one_todo_per_page(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    stats = run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    assert stats["links_planned"] == 3
    rows = load_todo(todo_path)
    assert len(rows) == 3
    for row in rows:
        assert row["stage"] == "lateral-link"
        assert row["kind"] == "page-link"
        assert row["response_schema"]["required"] == ["links"]
        assert "page_path" in row["context"]
        assert "sub" in row["context"]
        assert "stem" in row["context"]


def test_stage2_plan_is_idempotent(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    assert len(load_todo(todo_path)) == 3


def _write_done(done_path, todo_rows, link_map_by_stem):
    """Helper: build a done.jsonl matching the todo rows."""
    done_path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for row in todo_rows:
        stem = row["context"]["stem"]
        links = link_map_by_stem.get(stem, [])
        out.append({
            "job_id": row["job_id"],
            "response": {"links": links},
            "model": "test",
        })
    done_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n",
        encoding="utf-8",
    )


def test_stage2_finalize_merges_with_stage1(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    done_path = data_dir / "link.done.jsonl"
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    todos = load_todo(todo_path)
    _write_done(done_path, todos, {
        "alice": ["[[cross/some-theme]]"],
        "topic-a": ["[[cross/some-theme]]"],
        "alice--topic-a": [],
    })
    stats = run_stage2_finalize(tmp_wiki_dir, todo_path, done_path, data_dir)
    assert stats["missing"] == []
    assert stats["invalid"] == []
    pos = (tmp_wiki_dir / "positions" / "alice--topic-a.md").read_text(encoding="utf-8")
    assert "[[concepts/topic-a]]" in pos
    assert "[[people/alice]]" in pos
    person = (tmp_wiki_dir / "people" / "alice.md").read_text(encoding="utf-8")
    assert "[[cross/some-theme]]" in person
    assert "[[positions/alice--topic-a]]" in person


def test_stage2_finalize_filters_invalid_links(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    done_path = data_dir / "link.done.jsonl"
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    todos = load_todo(todo_path)
    _write_done(done_path, todos, {
        "alice": [
            "[[cross/valid]]",
            "not-a-wikilink",
            "[[people/alice]]",  # self-link, drop
            42,
            "[[concepts/orphan]]",
        ],
        "topic-a": [],
        "alice--topic-a": [],
    })
    run_stage2_finalize(tmp_wiki_dir, todo_path, done_path, data_dir)
    person = (tmp_wiki_dir / "people" / "alice.md").read_text(encoding="utf-8")
    assert "[[cross/valid]]" in person
    assert "[[concepts/orphan]]" in person
    assert "not-a-wikilink" not in person
    # The self-link must not appear as a stray bullet; it'd be `- [[people/alice]]`.
    assert "- [[people/alice]]" not in person


def test_stage2_finalize_caps_at_six(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    done_path = data_dir / "link.done.jsonl"
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    todos = load_todo(todo_path)
    over_cap = [f"[[cross/c{i}]]" for i in range(10)]
    _write_done(done_path, todos, {
        "alice": over_cap,
        "topic-a": [],
        "alice--topic-a": [],
    })
    run_stage2_finalize(tmp_wiki_dir, todo_path, done_path, data_dir)
    person = (tmp_wiki_dir / "people" / "alice.md").read_text(encoding="utf-8")
    kept = [f"[[cross/c{i}]]" for i in range(10) if f"[[cross/c{i}]]" in person]
    assert len(kept) == 6


def test_stage2_finalize_reports_missing_jobs(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    done_path = data_dir / "link.done.jsonl"
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    done_path.parent.mkdir(parents=True, exist_ok=True)
    done_path.write_text("", encoding="utf-8")
    stats = run_stage2_finalize(tmp_wiki_dir, todo_path, done_path, data_dir)
    assert len(stats["missing"]) == 3


def test_stage2_finalize_writes_link_graph(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    done_path = data_dir / "link.done.jsonl"
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    todos = load_todo(todo_path)
    _write_done(done_path, todos, {
        "alice": ["[[cross/x]]"],
        "topic-a": [],
        "alice--topic-a": [],
    })
    run_stage2_finalize(tmp_wiki_dir, todo_path, done_path, data_dir)
    graph_path = data_dir / "link_graph.jsonl"
    assert graph_path.exists()
    rows = [json.loads(l) for l in graph_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any("[[cross/x]]" in r["links"] for r in rows)


def test_stage2_finalize_records_invalid_response(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    done_path = data_dir / "link.done.jsonl"
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    todos = load_todo(todo_path)
    rows = [
        {"job_id": todos[0]["job_id"], "response": {"links": "not a list"}},
        {"job_id": todos[1]["job_id"], "response": {"links": []}},
        {"job_id": todos[2]["job_id"], "response": {"links": []}},
    ]
    done_path.parent.mkdir(parents=True, exist_ok=True)
    done_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    stats = run_stage2_finalize(tmp_wiki_dir, todo_path, done_path, data_dir)
    assert len(stats["invalid"]) == 1
    assert (data_dir / "link.failed.jsonl").exists()


def test_stable_job_id_used_for_links(tmp_wiki_dir, tmp_path):
    _seed(tmp_wiki_dir)
    data_dir = tmp_path / "data"
    todo_path = data_dir / "link.todo.jsonl"
    run_stage2_plan(tmp_wiki_dir, todo_path, data_dir)
    rows = load_todo(todo_path)
    for row in rows:
        expected = stable_job_id(
            row["stage"], row["kind"], row["system_prompt"], row["user_prompt"]
        )
        assert row["job_id"] == expected

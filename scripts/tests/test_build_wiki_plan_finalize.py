"""Round-trip tests for build_wiki_plan / build_wiki_finalize.

Plan walks plan_pages, emits one synthesis todo per planned page. Finalize
reads done.jsonl, validates bodies against the page schema, writes .md files.
Schema failures land in synthesis.failed.jsonl without aborting the rest.
"""
import json
from pathlib import Path

from signal_brain.wiki.build import build_wiki_plan, build_wiki_finalize
from signal_brain.worklist import load_todo


ME = {"sender_label": "Me", "slug": "thomas-martin", "name": "Thomas Martin"}


PERSON_BODY = """## Background
Background [B0001#m1].

## Style & drivers
Drives.

## Key positions
- [[positions/thomas-martin--topic-a]]

## Recurring moves
Moves.

## Open tensions
Tensions.

## Related
(auto-maintained — see link pass)
"""

CONCEPT_BODY = """## What's at stake
Stake.

## Sub-questions
Subs.

## Empirical anchors
Anchors [B0001#m1].

## Positions on this concept
- [[positions/thomas-martin--topic-a]]

## Related
(auto-maintained — see link pass)
"""

POSITION_BODY = """## Core claim
Claim.

## Reasoning chain
Chain [B0001#m1].

## Examples / evidence cited
Examples.

## Concessions made
None.

## Tensions with own other positions
None.

## Evolution timeline
None.

## Counter-arguments faced
None.

## Related
(auto-maintained — see link pass)
"""

CROSS_BODY = """## Overview
Overview.

## Instances
- [B0001#m1]: instance.

## Related
(auto-maintained — see link pass)
"""


def _seed_data(data_dir: Path, *, with_taxonomy: bool = True) -> None:
    """Write minimal bursts + chunks (+ taxonomy.json) under data_dir.

    Six bursts on `topic-a`, with `topic-a` listed as a taxonomy concept, gives:
    - 2 people pages (thomas-martin, friend)
    - 1 concept page (topic-a)
    - 2 position pages (one per person)
    - 4 cross seed pages (none exist on disk yet)

    With `with_taxonomy=False`, no taxonomy.json is written, so plan_pages
    receives an empty `concepts` list and plans no concept/position pages.
    """
    bursts = [
        {"id": f"B{i:04d}", "msg_ids": ["m1"], "start": "2026-05-05T13:00",
         "senders": {"Me": 1, "Friend": 1}}
        for i in range(1, 7)
    ]
    chunks = [
        {"burst_id": f"B{i:04d}", "primary": "topic-a",
         "topics": ["topic-a"], "summary": "discussed topic-a"}
        for i in range(1, 7)
    ]
    (data_dir / "bursts.jsonl").write_text(
        "\n".join(json.dumps(b) for b in bursts) + "\n", encoding="utf-8",
    )
    (data_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c) for c in chunks) + "\n", encoding="utf-8",
    )
    (data_dir / "arcs.jsonl").write_text("", encoding="utf-8")
    if with_taxonomy:
        (data_dir / "taxonomy.json").write_text(
            json.dumps({
                "source_hash": "sha1:test",
                "taxonomy": ["topic-a"],
                "concepts": ["topic-a"],
                "notes": "",
            }),
            encoding="utf-8",
        )


def test_plan_emits_one_todo_per_planned_page(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    wiki_dir = tmp_path / "wiki"
    todo_path = data_dir / "synthesis.todo.jsonl"
    _seed_data(data_dir)

    stats = build_wiki_plan(
        data_dir=data_dir, wiki_dir=wiki_dir, me=ME, todo_path=todo_path,
    )
    rows = load_todo(todo_path)
    assert stats["pages_planned"] == len(rows)
    kinds = sorted(r["kind"] for r in rows)
    # 2 person + 1 concept + 2 position + 4 cross seeds
    assert kinds.count("page-person") == 2
    assert kinds.count("page-concept") == 1
    assert kinds.count("page-position") == 2
    assert kinds.count("page-cross") == 4
    for row in rows:
        assert row["stage"] == "synthesis"
        assert "page_type" in row["context"]
        assert "out_path" in row["context"]
        assert "frontmatter" in row["context"]


def test_finalize_writes_md_files_for_each_done_row(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    wiki_dir = tmp_path / "wiki"
    todo_path = data_dir / "synthesis.todo.jsonl"
    done_path = data_dir / "synthesis.done.jsonl"
    _seed_data(data_dir)

    build_wiki_plan(
        data_dir=data_dir, wiki_dir=wiki_dir, me=ME, todo_path=todo_path,
    )
    bodies = {
        "page-person": PERSON_BODY, "page-concept": CONCEPT_BODY,
        "page-position": POSITION_BODY, "page-cross": CROSS_BODY,
    }
    rows = load_todo(todo_path)
    with done_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({
                "job_id": row["job_id"],
                "response": {"body": bodies[row["kind"]]},
                "model": "test", "elapsed_s": 0.0,
            }) + "\n")

    stats = build_wiki_finalize(
        data_dir=data_dir, wiki_dir=wiki_dir,
        todo_path=todo_path, done_path=done_path,
    )
    assert stats["pages_written"] == len(rows)
    assert stats["failed"] == 0
    assert stats["missing"] == []
    for row in rows:
        out_path = Path(row["context"]["out_path"])
        assert out_path.exists(), f"missing {out_path}"
        text = out_path.read_text(encoding="utf-8")
        assert text.startswith("---\n")


def test_finalize_records_schema_failure_without_writing(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    wiki_dir = tmp_path / "wiki"
    todo_path = data_dir / "synthesis.todo.jsonl"
    done_path = data_dir / "synthesis.done.jsonl"
    _seed_data(data_dir)

    build_wiki_plan(
        data_dir=data_dir, wiki_dir=wiki_dir, me=ME, todo_path=todo_path,
    )
    rows = load_todo(todo_path)
    target = next(r for r in rows if r["kind"] == "page-person")
    bad_body = "## Background\nOnly one section, no others.\n"
    # Give every other row a valid body so we can isolate the one failure.
    bodies = {
        "page-person": PERSON_BODY, "page-concept": CONCEPT_BODY,
        "page-position": POSITION_BODY, "page-cross": CROSS_BODY,
    }
    with done_path.open("w", encoding="utf-8") as f:
        for row in rows:
            body = bad_body if row["job_id"] == target["job_id"] else bodies[row["kind"]]
            f.write(json.dumps({
                "job_id": row["job_id"],
                "response": {"body": body},
                "model": "test", "elapsed_s": 0.0,
            }) + "\n")

    stats = build_wiki_finalize(
        data_dir=data_dir, wiki_dir=wiki_dir,
        todo_path=todo_path, done_path=done_path,
    )
    assert stats["failed"] == 1
    assert stats["pages_written"] == len(rows) - 1
    bad_path = Path(target["context"]["out_path"])
    assert not bad_path.exists()
    failed_path = data_dir / "synthesis.failed.jsonl"
    assert failed_path.exists()
    failed_rows = [json.loads(l) for l in failed_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(failed_rows) == 1
    assert failed_rows[0]["job_id"] == target["job_id"]
    assert failed_rows[0]["page_type"] == "person"
    assert "Missing sections" in failed_rows[0]["error"]


def test_build_wiki_plan_no_taxonomy_json_plans_no_concepts(tmp_path):
    """Without taxonomy.json, concepts is empty: no concept/position pages,
    but people/arc/cross pages are still planned."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    wiki_dir = tmp_path / "wiki"
    todo_path = data_dir / "synthesis.todo.jsonl"
    _seed_data(data_dir, with_taxonomy=False)
    assert not (data_dir / "taxonomy.json").exists()

    build_wiki_plan(
        data_dir=data_dir, wiki_dir=wiki_dir, me=ME, todo_path=todo_path,
    )
    rows = load_todo(todo_path)
    kinds = [r["kind"] for r in rows]
    assert kinds.count("page-concept") == 0
    assert kinds.count("page-position") == 0
    # People and cross pages are independent of the taxonomy.
    assert kinds.count("page-person") == 2
    assert kinds.count("page-cross") == 4

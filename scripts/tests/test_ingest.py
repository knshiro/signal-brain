"""Tests for the two-phase ingest pipeline."""
import json
from signal_brain.ingest import (
    diff_messages,
    run_ingest_plan,
    run_ingest_finalize,
)
from signal_brain.worklist import load_todo


def test_diff_messages_identifies_new_and_modified(tmp_data_dir):
    existing = [
        {"msg_id": "2026-05-05T13:00:00::Me", "date": "2026-05-05T13:00:00",
         "sender": "Me", "body": "hi", "quote": "", "reactions": [],
         "attachments": [], "char_count": 2},
    ]
    (tmp_data_dir / "msg_index.jsonl").write_text(
        "\n".join(json.dumps(r) for r in existing) + "\n", encoding="utf-8"
    )
    new_input = [
        {"date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi",
         "quote": "", "reactions": [], "attachments": []},
        {"date": "2026-05-05T13:05:00", "sender": "Friend", "body": "yo",
         "quote": "", "reactions": [], "attachments": []},
    ]
    diff = diff_messages(new_input, tmp_data_dir / "msg_index.jsonl")
    assert len(diff["new"]) == 1
    assert diff["new"][0]["sender"] == "Friend"
    assert len(diff["modified"]) == 0


def test_run_ingest_plan_emits_tagging_todos(tmp_path, mini_messages):
    src = tmp_path / "out" / "Friend"
    src.mkdir(parents=True)
    (src / "data.json").write_text(
        "\n".join(json.dumps(m) for m in mini_messages) + "\n", encoding="utf-8"
    )
    data_dir = tmp_path / "data"

    stats = run_ingest_plan(
        source_path=src / "data.json",
        data_dir=data_dir,
        burst_threshold_min=60,
    )
    # L1 artifacts produced — no chunks/arcs yet
    assert (data_dir / "msg_index.jsonl").exists()
    assert (data_dir / "bursts.jsonl").exists()
    assert (data_dir / "tagging.todo.jsonl").exists()
    assert not (data_dir / "chunks.jsonl").exists()
    assert not (data_dir / "arcs.jsonl").exists()

    todos = load_todo(data_dir / "tagging.todo.jsonl")
    assert stats["tagging_todos"] == len(todos) > 0
    assert all(t["stage"] == "tagging" for t in todos)


def test_plan_finalize_round_trip_writes_all_artifacts(tmp_path, mini_messages):
    """Simulate the agent's middle step by writing fake done rows."""
    src = tmp_path / "out" / "Friend"
    src.mkdir(parents=True)
    (src / "data.json").write_text(
        "\n".join(json.dumps(m) for m in mini_messages) + "\n", encoding="utf-8"
    )
    data_dir = tmp_path / "data"

    run_ingest_plan(source_path=src / "data.json",
                    data_dir=data_dir, burst_threshold_min=60)

    # Hand-write done rows for every todo: the agent's role.
    todos = load_todo(data_dir / "tagging.todo.jsonl")
    done_rows = [
        {"job_id": t["job_id"],
         "response": {"topics": ["banter"], "primary": "banter",
                      "summary": "banter sample"}}
        for t in todos
    ]
    (data_dir / "tagging.done.jsonl").write_text(
        "\n".join(json.dumps(r) for r in done_rows) + "\n", encoding="utf-8"
    )

    stats = run_ingest_finalize(
        data_dir=data_dir, min_burst_count=2, min_msg_count=20,
    )
    for f in ["msg_index.jsonl", "bursts.jsonl", "chunks.jsonl",
              "arcs.jsonl", "manifest.json"]:
        assert (data_dir / f).exists(), f
    assert stats["tagging"]["missing"] == []
    assert stats["tagging"]["invalid"] == []
    assert stats["tagging"]["new"] == len(todos)


def test_replan_after_finalize_emits_no_new_todos(tmp_path, mini_messages):
    """If nothing changes, re-running plan should produce zero new todo rows.

    The cache (chunks + manifest hashes) recognizes every burst as unchanged.
    """
    src = tmp_path / "out" / "Friend"
    src.mkdir(parents=True)
    (src / "data.json").write_text(
        "\n".join(json.dumps(m) for m in mini_messages) + "\n", encoding="utf-8"
    )
    data_dir = tmp_path / "data"
    run_ingest_plan(source_path=src / "data.json",
                    data_dir=data_dir, burst_threshold_min=60)
    todos1 = load_todo(data_dir / "tagging.todo.jsonl")
    done_rows = [
        {"job_id": t["job_id"],
         "response": {"topics": ["banter"], "primary": "banter", "summary": "."}}
        for t in todos1
    ]
    (data_dir / "tagging.done.jsonl").write_text(
        "\n".join(json.dumps(r) for r in done_rows) + "\n", encoding="utf-8"
    )
    run_ingest_finalize(data_dir=data_dir, min_burst_count=2, min_msg_count=20)

    # Re-plan: existing todo file is still there but emit() dedupes by job_id,
    # AND cache hits skip emission entirely. Either way, no NEW rows beyond
    # what was already there.
    (data_dir / "tagging.todo.jsonl").unlink()  # simulate fresh plan
    stats = run_ingest_plan(source_path=src / "data.json",
                            data_dir=data_dir, burst_threshold_min=60)
    assert stats["tagging_todos"] == 0

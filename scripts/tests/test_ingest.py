"""Tests for the two-phase ingest pipeline."""
import json
from signal_brain.ingest import (
    diff_messages,
    run_ingest_plan,
    run_ingest_finalize,
)
from signal_brain.worklist import load_todo


def _complete_taxonomy_stage(data_dir, *, taxonomy=("banter", "small-talk")):
    """Drive the taxonomy stage of the staged plan.

    `run_ingest_plan` is self-progressing: its first call emits a taxonomy
    todo. This helper writes the matching `taxonomy.done.jsonl` row so a
    subsequent `run_ingest_plan` call finalizes the taxonomy and moves on to
    emitting tagging todos.
    """
    todos = load_todo(data_dir / "taxonomy.todo.jsonl")
    assert len(todos) == 1, f"expected one taxonomy todo, got {len(todos)}"
    done_row = {
        "job_id": todos[0]["job_id"],
        "response": {"taxonomy": list(taxonomy), "concepts": list(taxonomy),
                     "notes": "test taxonomy"},
    }
    (data_dir / "taxonomy.done.jsonl").write_text(
        json.dumps(done_row) + "\n", encoding="utf-8"
    )


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

    # First call: staged plan emits a taxonomy todo, not tagging todos.
    run_ingest_plan(
        source_path=src / "data.json",
        data_dir=data_dir,
        burst_threshold_min=60,
    )
    _complete_taxonomy_stage(data_dir)

    # Second call: taxonomy is finalized, tagging todos are emitted.
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

    # Staged plan: first call emits a taxonomy todo, second emits tagging todos.
    run_ingest_plan(source_path=src / "data.json",
                    data_dir=data_dir, burst_threshold_min=60)
    _complete_taxonomy_stage(data_dir)
    run_ingest_plan(source_path=src / "data.json",
                    data_dir=data_dir, burst_threshold_min=60)

    # Hand-write done rows for every todo: the agent's role.
    todos = load_todo(data_dir / "tagging.todo.jsonl")
    done_rows = [
        {"job_id": t["job_id"],
         "response": {"topics": ["banter"], "primary": "banter",
                      "summary": "banter sample", "out_of_taxonomy": False}}
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
    # Staged plan: first call emits a taxonomy todo, second emits tagging todos.
    run_ingest_plan(source_path=src / "data.json",
                    data_dir=data_dir, burst_threshold_min=60)
    _complete_taxonomy_stage(data_dir)
    run_ingest_plan(source_path=src / "data.json",
                    data_dir=data_dir, burst_threshold_min=60)
    todos1 = load_todo(data_dir / "tagging.todo.jsonl")
    done_rows = [
        {"job_id": t["job_id"],
         "response": {"topics": ["banter"], "primary": "banter", "summary": ".",
                      "out_of_taxonomy": False}}
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


def test_run_ingest_plan_emits_taxonomy_todo_when_no_cache(tmp_path):
    """First call: no taxonomy.json -> emit taxonomy todo, suppress tagging todos."""
    source = tmp_path / "src.jsonl"
    source.write_text("\n".join([
        json.dumps({"date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi"}),
        json.dumps({"date": "2026-05-05T13:00:01", "sender": "Friend", "body": "salut"}),
    ]) + "\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    stats = run_ingest_plan(
        source_path=source, data_dir=data_dir, burst_threshold_min=60,
    )
    assert stats["taxonomy_pending"] is True
    assert stats["taxonomy_todos"] == 1
    assert stats["tagging_todos"] == 0
    assert (data_dir / "taxonomy.todo.jsonl").exists()
    tagging_todo = data_dir / "tagging.todo.jsonl"
    assert not tagging_todo.exists() or \
        sum(1 for _ in tagging_todo.open(encoding="utf-8")) == 0


def test_run_ingest_plan_emits_tagging_when_taxonomy_cache_hit(tmp_path):
    """Second call: taxonomy.json with matching hash -> emit tagging with required vocab."""
    source = tmp_path / "src.jsonl"
    source.write_text("\n".join([
        json.dumps({"date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi"}),
        json.dumps({"date": "2026-05-05T13:00:01", "sender": "Friend", "body": "salut"}),
    ]) + "\n", encoding="utf-8")
    data_dir = tmp_path / "data"

    # First call produces msg_index + the taxonomy todo.
    run_ingest_plan(source_path=source, data_dir=data_dir, burst_threshold_min=60)

    # Compute the hash run_ingest_plan will use and prime taxonomy.json.
    from signal_brain.msg_index import load_msg_index
    from signal_brain.taxonomy import source_content_hash
    msgs = load_msg_index(data_dir / "msg_index.jsonl")
    expected_hash = source_content_hash(msgs)
    (data_dir / "taxonomy.json").write_text(json.dumps({
        "source_hash": expected_hash,
        "taxonomy": ["greeting", "small-talk"],
        "concepts": ["small-talk"],
        "notes": "",
    }), encoding="utf-8")

    stats = run_ingest_plan(source_path=source, data_dir=data_dir, burst_threshold_min=60)
    assert stats["taxonomy_pending"] is False
    assert stats["tagging_todos"] >= 1
    row = json.loads((data_dir / "tagging.todo.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "Required vocabulary" in row["user_prompt"]
    assert "greeting" in row["user_prompt"]


def test_run_ingest_finalize_writes_taxonomy_json_from_done(tmp_path):
    """If taxonomy.done has a row matching the current source_hash, finalize writes the cache."""
    source = tmp_path / "src.jsonl"
    source.write_text(json.dumps({
        "date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi"
    }) + "\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    # Drive a plan to produce taxonomy.todo and msg_index.
    run_ingest_plan(source_path=source, data_dir=data_dir, burst_threshold_min=60)
    todo_row = load_todo(data_dir / "taxonomy.todo.jsonl")[0]
    (data_dir / "taxonomy.done.jsonl").write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {"taxonomy": ["greeting"], "concepts": [], "notes": "n/a"},
    }) + "\n", encoding="utf-8")

    run_ingest_finalize(data_dir=data_dir, min_burst_count=2, min_msg_count=20)
    data = json.loads((data_dir / "taxonomy.json").read_text(encoding="utf-8"))
    assert data["taxonomy"] == ["greeting"]


def test_run_ingest_plan_scrubs_real_names_when_configured(tmp_path):
    """End-to-end: configuring real_names removes the literal from msg_index.jsonl."""
    source = tmp_path / "src.jsonl"
    source.write_text(json.dumps({
        "date": "2026-05-05T13:18:00.000000",
        "sender": "Friend",
        "body": "Salut Ugo, ça va ?",
        "quote": "",
        "reactions": [],
        "attachments": [],
    }) + "\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    run_ingest_plan(
        source_path=source,
        data_dir=data_dir,
        burst_threshold_min=60,
        me_real_names=["Ugo"],
        me_name="Thomas Martin",
    )
    body = (data_dir / "msg_index.jsonl").read_text(encoding="utf-8")
    assert "Ugo" not in body
    assert "Thomas" in body

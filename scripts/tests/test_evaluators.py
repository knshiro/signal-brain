"""Tests for the burst-evaluator plan/finalize pipeline."""
import json
import random

from signal_brain.evaluators import (
    evaluate_bursts_finalize,
    evaluate_bursts_plan,
)
from signal_brain.worklist import load_todo


def _seed_data_dir(data_dir, n_bursts=5):
    """Write a small bursts.jsonl + msg_index.jsonl for testing."""
    data_dir.mkdir(parents=True, exist_ok=True)
    msgs = []
    bursts = []
    for b in range(n_bursts):
        ids = []
        for j in range(4):
            mid = f"M{b}_{j}"
            msgs.append({
                "msg_id": mid,
                "sender": "Alice" if j % 2 == 0 else "Friend",
                "body": f"burst {b} msg {j}",
                "date": f"2026-01-01T0{b}:0{j}:00Z",
            })
            ids.append(mid)
        bursts.append({
            "id": f"B{b:04d}",
            "msg_ids": ids,
            "start": f"2026-01-01T0{b}:00:00Z",
            "end": f"2026-01-01T0{b}:03:00Z",
        })
    (data_dir / "msg_index.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n",
        encoding="utf-8",
    )
    (data_dir / "bursts.jsonl").write_text(
        "\n".join(json.dumps(b, ensure_ascii=False) for b in bursts) + "\n",
        encoding="utf-8",
    )
    return bursts


def test_plan_emits_one_todo_per_sampled_boundary(tmp_path):
    data_dir = tmp_path / "data"
    _seed_data_dir(data_dir, n_bursts=5)
    todo_path = data_dir / "eval.todo.jsonl"
    random.seed(0)
    stats = evaluate_bursts_plan(data_dir, todo_path, sample_size=3)
    assert stats["sampled"] == 3
    rows = load_todo(todo_path)
    assert len(rows) == 3
    for row in rows:
        assert row["stage"] == "evaluate-bursts"
        assert row["kind"] == "boundary"
        assert "boundary" in row["context"]
        assert len(row["context"]["boundary"]) == 2
        assert row["response_schema"]["required"] == ["verdict", "rationale"]


def test_plan_caps_at_available_boundaries(tmp_path):
    data_dir = tmp_path / "data"
    _seed_data_dir(data_dir, n_bursts=3)
    todo_path = data_dir / "eval.todo.jsonl"
    stats = evaluate_bursts_plan(data_dir, todo_path, sample_size=50)
    # Only 2 boundaries possible from 3 bursts.
    assert stats["sampled"] == 2


def test_plan_handles_too_few_bursts(tmp_path):
    data_dir = tmp_path / "data"
    _seed_data_dir(data_dir, n_bursts=1)
    todo_path = data_dir / "eval.todo.jsonl"
    stats = evaluate_bursts_plan(data_dir, todo_path, sample_size=5)
    assert stats["sampled"] == 0
    assert stats["verdict"] == "not-enough-bursts"


def _write_done(done_path, todo_rows, verdicts):
    """Helper: build done.jsonl with verdicts cycling through `verdicts`."""
    rows = []
    for i, todo in enumerate(todo_rows):
        v = verdicts[i % len(verdicts)]
        rows.append({
            "job_id": todo["job_id"],
            "response": {"verdict": v, "rationale": f"because {v}"},
        })
    done_path.parent.mkdir(parents=True, exist_ok=True)
    done_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def test_finalize_aggregates_verdict_counts(tmp_path):
    data_dir = tmp_path / "data"
    _seed_data_dir(data_dir, n_bursts=5)
    todo_path = data_dir / "eval.todo.jsonl"
    done_path = data_dir / "eval.done.jsonl"
    random.seed(0)
    evaluate_bursts_plan(data_dir, todo_path, sample_size=4)
    todos = load_todo(todo_path)
    _write_done(done_path, todos, ["natural", "should-merge", "natural", "should-split-elsewhere"])
    result = evaluate_bursts_finalize(todo_path, done_path)
    assert result["n"] == 4
    assert result["counts"]["natural"] == 2
    assert result["counts"]["should-merge"] == 1
    assert result["counts"]["should-split-elsewhere"] == 1
    assert len(result["samples"]) == 4
    assert result["missing"] == []
    assert result["invalid"] == []


def test_finalize_reports_missing(tmp_path):
    data_dir = tmp_path / "data"
    _seed_data_dir(data_dir, n_bursts=5)
    todo_path = data_dir / "eval.todo.jsonl"
    done_path = data_dir / "eval.done.jsonl"
    evaluate_bursts_plan(data_dir, todo_path, sample_size=3)
    done_path.parent.mkdir(parents=True, exist_ok=True)
    done_path.write_text("", encoding="utf-8")
    result = evaluate_bursts_finalize(todo_path, done_path)
    assert result["n"] == 0
    assert len(result["missing"]) == 3


def test_finalize_reports_invalid(tmp_path):
    data_dir = tmp_path / "data"
    _seed_data_dir(data_dir, n_bursts=5)
    todo_path = data_dir / "eval.todo.jsonl"
    done_path = data_dir / "eval.done.jsonl"
    evaluate_bursts_plan(data_dir, todo_path, sample_size=2)
    todos = load_todo(todo_path)
    rows = [
        {"job_id": todos[0]["job_id"], "response": {"verdict": "natural"}},  # missing rationale
        {"job_id": todos[1]["job_id"], "response": {"verdict": "natural", "rationale": "ok"}},
    ]
    done_path.parent.mkdir(parents=True, exist_ok=True)
    done_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    result = evaluate_bursts_finalize(todo_path, done_path)
    assert len(result["invalid"]) == 1
    assert result["counts"]["natural"] == 1

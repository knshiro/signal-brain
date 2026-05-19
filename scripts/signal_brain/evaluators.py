"""Burst-threshold evaluator — plan/finalize.

`evaluate_bursts_plan` samples N boundaries from `bursts.jsonl` and emits one
todo row per boundary. `evaluate_bursts_finalize` reads matching done rows and
aggregates verdict counts. Neither phase calls an LLM directly.
"""
from __future__ import annotations
import json
import random
from pathlib import Path

from signal_brain.msg_index import load_msg_index
from signal_brain.worklist import (
    WorklistError,
    emit,
    load_done,
    load_todo,
    validate_response,
)


EVAL_SYSTEM = """You evaluate whether a burst boundary in a Signal conversation is natural.

You are shown the last 3 messages of burst K and the first 3 of burst K+1.
Output VALID JSON. No prose around.
{"verdict": "natural" | "should-merge" | "should-split-elsewhere", "rationale": "..."}
"""


EVAL_USER = """End of burst {k} ({k_end_time}):
{k_tail}

Start of burst {k_plus_1} ({k1_start_time}):
{k1_head}

Was this a natural conversation break?"""


EVAL_RESPONSE_SCHEMA = {
    "required": ["verdict", "rationale"],
    "types": {"verdict": "str", "rationale": "str"},
}


def evaluate_bursts_plan(
    data_dir: Path,
    todo_path: Path,
    sample_size: int = 20,
) -> dict:
    """Sample boundaries from bursts.jsonl, emit one todo row per boundary."""
    data_dir = Path(data_dir)
    bursts = [
        json.loads(l) for l in
        (data_dir / "bursts.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    if len(bursts) < 2:
        return {"sampled": 0, "verdict": "not-enough-bursts"}
    msgs = {m["msg_id"]: m for m in load_msg_index(data_dir / "msg_index.jsonl")}
    sample_idx = random.sample(range(len(bursts) - 1), min(sample_size, len(bursts) - 1))
    for i in sample_idx:
        k, k1 = bursts[i], bursts[i + 1]
        k_tail = "\n".join(
            f"{msgs[mid]['sender']}: {msgs[mid].get('body', '').strip()}"
            for mid in k["msg_ids"][-3:]
        )
        k1_head = "\n".join(
            f"{msgs[mid]['sender']}: {msgs[mid].get('body', '').strip()}"
            for mid in k1["msg_ids"][:3]
        )
        user = EVAL_USER.format(
            k=k["id"], k_end_time=k["end"], k_tail=k_tail,
            k_plus_1=k1["id"], k1_start_time=k1["start"], k1_head=k1_head,
        )
        emit(
            todo_path,
            stage="evaluate-bursts",
            kind="boundary",
            system=EVAL_SYSTEM,
            user=user,
            response_schema=EVAL_RESPONSE_SCHEMA,
            context={"boundary": [k["id"], k1["id"]]},
        )
    return {"sampled": len(sample_idx)}


def evaluate_bursts_finalize(todo_path: Path, done_path: Path) -> dict:
    """Read todo+done pairs and aggregate verdict counts."""
    todos = load_todo(todo_path)
    done_by_job = load_done(done_path)
    counts: dict[str, int] = {"natural": 0, "should-merge": 0, "should-split-elsewhere": 0}
    samples: list[dict] = []
    missing: list[str] = []
    invalid: list[str] = []
    for todo in todos:
        boundary = todo.get("context", {}).get("boundary")
        done = done_by_job.get(todo["job_id"])
        if done is None:
            missing.append(todo["job_id"])
            continue
        resp = done.get("response", {})
        try:
            validate_response(resp, todo["response_schema"])
        except WorklistError:
            invalid.append(todo["job_id"])
            continue
        verdict = resp.get("verdict", "should-split-elsewhere")
        counts[verdict] = counts.get(verdict, 0) + 1
        samples.append({
            "boundary": boundary,
            "verdict": verdict,
            "rationale": resp.get("rationale", ""),
        })
    return {
        "counts": counts,
        "samples": samples,
        "n": len(samples),
        "missing": missing,
        "invalid": invalid,
    }

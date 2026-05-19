"""One-shot burst-threshold evaluator."""
from __future__ import annotations
import json
import random
from pathlib import Path
from signal_brain.msg_index import load_msg_index


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


def evaluate_bursts(data_dir: Path, llm, sample_size: int = 20) -> dict:
    data_dir = Path(data_dir)
    bursts = [json.loads(l) for l in (data_dir / "bursts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    msgs = {m["msg_id"]: m for m in load_msg_index(data_dir / "msg_index.jsonl")}
    if len(bursts) < 2:
        return {"verdict": "not-enough-bursts", "samples": []}
    sample_idx = random.sample(range(len(bursts) - 1), min(sample_size, len(bursts) - 1))
    results = []
    for i in sample_idx:
        k, k1 = bursts[i], bursts[i + 1]
        k_tail = "\n".join(
            f"{msgs[mid]['sender']}: {msgs[mid].get('body','').strip()}"
            for mid in k["msg_ids"][-3:]
        )
        k1_head = "\n".join(
            f"{msgs[mid]['sender']}: {msgs[mid].get('body','').strip()}"
            for mid in k1["msg_ids"][:3]
        )
        verdict = llm.complete_json(EVAL_SYSTEM, EVAL_USER.format(
            k=k["id"], k_end_time=k["end"], k_tail=k_tail,
            k_plus_1=k1["id"], k1_start_time=k1["start"], k1_head=k1_head,
        ))
        results.append({"boundary": [k["id"], k1["id"]], **verdict})
    counts: dict[str, int] = {"natural": 0, "should-merge": 0, "should-split-elsewhere": 0}
    for r in results:
        v = r.get("verdict", "should-split-elsewhere")
        counts[v] = counts.get(v, 0) + 1
    return {"counts": counts, "samples": results, "n": len(results)}

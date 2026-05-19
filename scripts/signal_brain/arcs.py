"""L2b: arc detection from per-burst tags."""
from __future__ import annotations
import json
from pathlib import Path


def detect_arcs(bursts: list[dict], chunks: list[dict],
                min_burst_count: int, min_msg_count: int) -> list[dict]:
    by_id = {c["burst_id"]: c for c in chunks}
    bursts_by_id = {b["id"]: b for b in bursts}
    runs: list[list[str]] = []
    current: list[str] = []
    current_topic = None
    for b in bursts:
        primary = by_id.get(b["id"], {}).get("primary")
        if primary == current_topic and primary is not None:
            current.append(b["id"])
        else:
            if current:
                runs.append(current)
            current = [b["id"]] if primary else []
            current_topic = primary
    if current:
        runs.append(current)

    arcs = []
    for run in runs:
        if len(run) < min_burst_count:
            continue
        msg_count = sum(len(bursts_by_id[bid]["msg_ids"]) for bid in run)
        if msg_count < min_msg_count:
            continue
        primary = by_id[run[0]]["primary"]
        idx = len(arcs) + 1
        arcs.append({
            "id": f"A{idx:03d}",
            "slug": f"{primary}-{run[0]}-{run[-1]}".replace("_", "-"),
            "period": [bursts_by_id[run[0]]["start"][:10], bursts_by_id[run[-1]]["end"][:10]],
            "primary": primary,
            "bursts": run,
            "status": "unresolved",
            "msg_count": msg_count,
        })
    return arcs


def write_arcs(arcs: list[dict], out_path: Path) -> None:
    Path(out_path).write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in arcs) + "\n",
        encoding="utf-8",
    )

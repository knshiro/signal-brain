"""L1: time-gap burst detection and per-burst content hashing."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


def _parse(ts: str) -> datetime:
    # Accept "...000000" or "...000Z"
    return datetime.fromisoformat(ts.replace("Z", ""))


def detect_bursts(messages: list[dict], threshold_min: int) -> list[dict]:
    """Split messages into bursts when consecutive-gap > threshold."""
    if not messages:
        return []
    threshold = timedelta(minutes=threshold_min)
    bursts: list[dict] = []
    current: list[dict] = [messages[0]]
    prev_ts = _parse(messages[0]["date"])
    for m in messages[1:]:
        ts = _parse(m["date"])
        if ts - prev_ts > threshold:
            bursts.append(_finalize(current, len(bursts) + 1))
            current = []
        current.append(m)
        prev_ts = ts
    if current:
        bursts.append(_finalize(current, len(bursts) + 1))
    return bursts


def _finalize(msgs: list[dict], idx: int) -> dict:
    senders: dict[str, int] = {}
    chars = 0
    has_media = False
    for m in msgs:
        senders[m["sender"]] = senders.get(m["sender"], 0) + 1
        chars += m.get("char_count", len(m.get("body", "")))
        if m.get("attachments"):
            has_media = True
    return {
        "id": f"B{idx:04d}",
        "start": msgs[0]["date"],
        "end": msgs[-1]["date"],
        "msg_ids": [m["msg_id"] for m in msgs],
        "senders": senders,
        "char_count": chars,
        "has_media": has_media,
    }


def burst_content_hash(burst: dict, all_messages: list[dict]) -> str:
    """SHA1 over msg_id + body + reactions for every message in the burst."""
    by_id = {m["msg_id"]: m for m in all_messages}
    h = hashlib.sha1()
    for mid in burst["msg_ids"]:
        m = by_id[mid]
        h.update(mid.encode())
        h.update(b"\x00")
        h.update(m.get("body", "").encode())
        h.update(b"\x00")
        h.update(json.dumps(m.get("reactions", []), sort_keys=True).encode())
        h.update(b"\x01")
    return f"sha1:{h.hexdigest()}"


def write_bursts(bursts: list[dict], out_path: Path) -> None:
    Path(out_path).write_text(
        "\n".join(json.dumps(b, ensure_ascii=False) for b in bursts) + "\n",
        encoding="utf-8",
    )

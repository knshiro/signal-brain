"""Stable message IDs and the flat addressable message index."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable


def msg_id(msg: dict) -> str:
    """`{ISO-timestamp}::{sender}`. Composite breaks rare millisecond ties."""
    return f"{msg['date']}::{msg['sender']}"


def build_msg_index(messages: Iterable[dict], out_path: Path) -> int:
    """Write deduplicated msg_index.jsonl. Returns row count."""
    seen: set[str] = set()
    rows = []
    for m in messages:
        mid = msg_id(m)
        if mid in seen:
            continue
        seen.add(mid)
        rows.append({
            "msg_id": mid,
            "date": m["date"],
            "sender": m["sender"],
            "body": m.get("body", ""),
            "quote": m.get("quote", ""),
            "reactions": m.get("reactions", []),
            "attachments": m.get("attachments", []),
            "char_count": len(m.get("body", "")),
        })
    Path(out_path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return len(rows)


def load_msg_index(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

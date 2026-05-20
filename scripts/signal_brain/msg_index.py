"""Stable message IDs and the flat addressable message index."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Callable, Iterable


def msg_id(msg: dict) -> str:
    """`{ISO-timestamp}::{sender}`. Composite breaks rare millisecond ties."""
    return f"{msg['date']}::{msg['sender']}"


def build_msg_index(
    messages: Iterable[dict],
    out_path: Path,
    *,
    scrub: Callable[[str], str] | None = None,
) -> int:
    """Write deduplicated msg_index.jsonl. Returns row count.

    If `scrub` is provided, it's applied to the `body` and `quote` fields, and
    to the reactor-name slot of each reaction entry (`reactions[*][0]`) before
    rows are written. The resulting `char_count` reflects the post-scrub body.
    """
    apply = scrub or (lambda s: s)
    seen: set[str] = set()
    rows = []
    for m in messages:
        mid = msg_id(m)
        if mid in seen:
            continue
        seen.add(mid)
        body = apply(m.get("body", ""))
        quote = apply(m.get("quote", ""))
        scrubbed_reactions = []
        for r in m.get("reactions", []):
            if isinstance(r, list) and r and isinstance(r[0], str):
                scrubbed_reactions.append([apply(r[0]), *r[1:]])
            else:
                scrubbed_reactions.append(r)
        rows.append({
            "msg_id": mid,
            "date": m["date"],
            "sender": m["sender"],
            "body": body,
            "quote": quote,
            "reactions": scrubbed_reactions,
            "attachments": m.get("attachments", []),
            "char_count": len(body),
        })
    Path(out_path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return len(rows)


def load_msg_index(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

"""Citation format `[B0042#m17]` → message resolution."""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path


CITATION_RE = re.compile(r"\[B(\d{4})#m(\d+)\]")


class UnresolvedCitation(Exception):
    pass


def parse_citation(cite: str) -> tuple[str, int]:
    m = CITATION_RE.fullmatch(cite)
    if not m:
        raise ValueError(f"Bad citation: {cite!r}")
    return f"B{m.group(1)}", int(m.group(2))


def find_citations(text: str) -> list[str]:
    return [m.group(0) for m in CITATION_RE.finditer(text)]


@lru_cache(maxsize=4)
def _load(data_dir: Path) -> tuple[dict, dict]:
    data_dir = Path(data_dir)
    bursts_path = data_dir / "bursts.jsonl"
    msgs_path = data_dir / "msg_index.jsonl"
    bursts: dict[str, dict] = {}
    if bursts_path.exists() and bursts_path.read_text(encoding="utf-8").strip():
        for line in bursts_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                b = json.loads(line)
                bursts[b["id"]] = b
    msgs: dict[str, dict] = {}
    if msgs_path.exists() and msgs_path.read_text(encoding="utf-8").strip():
        for line in msgs_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                m = json.loads(line)
                msgs[m["msg_id"]] = m
    return bursts, msgs


def resolve_citation(cite: str, data_dir: Path) -> dict:
    burst_id, m_idx = parse_citation(cite)
    bursts, msgs = _load(Path(data_dir))
    if burst_id not in bursts:
        raise UnresolvedCitation(cite)
    msg_ids = bursts[burst_id]["msg_ids"]
    if m_idx < 1 or m_idx > len(msg_ids):
        raise UnresolvedCitation(cite)
    mid = msg_ids[m_idx - 1]  # 1-indexed in citations, 0-indexed in list
    if mid not in msgs:
        raise UnresolvedCitation(cite)
    return msgs[mid]


def render_citation(cite: str, data_dir: Path) -> str:
    msg = resolve_citation(cite, data_dir)
    return f"({msg['date'][:16].replace('T', ' ')}, {msg['sender']}): {msg['body']!r}"

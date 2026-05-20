"""Incremental ingest pipeline — plan/finalize.

`run_ingest_plan` builds the deterministic L1 layer (msg_index, bursts) and
emits a tagging todo file. The agent then fills in the done file by dispatching
subagents. `run_ingest_finalize` reads the done file, writes chunks.jsonl, and
runs the deterministic L2b layer (arcs + manifest).

Neither phase calls an LLM directly.
"""
from __future__ import annotations

import json
from pathlib import Path

from signal_brain.msg_index import build_msg_index, load_msg_index, msg_id
from signal_brain.bursts import detect_bursts, write_bursts
from signal_brain.tagging import (
    emit_tagging_todos,
    finalize_tagging,
    load_chunks_as_cache,
)
from signal_brain.arcs import detect_arcs, write_arcs
from signal_brain.manifest import Manifest
from signal_brain.anonymize import compile_scrubber


def _load_raw(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def diff_messages(new_input: list[dict], existing_index_path: Path) -> dict:
    """Return dict with keys: new, modified, removed, unchanged_count."""
    existing = {}
    if Path(existing_index_path).exists():
        for line in Path(existing_index_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            existing[r["msg_id"]] = r
    new_ids = set()
    new_list: list[dict] = []
    modified: list[dict] = []
    for m in new_input:
        mid = msg_id(m)
        new_ids.add(mid)
        if mid not in existing:
            new_list.append(m)
        else:
            prev = existing[mid]
            if (m.get("body", "") != prev.get("body", "")
                    or m.get("reactions", []) != prev.get("reactions", [])
                    or m.get("attachments", []) != prev.get("attachments", [])):
                modified.append(m)
    removed = [mid for mid in existing if mid not in new_ids]
    return {"new": new_list, "modified": modified, "removed": removed,
            "unchanged_count": len(existing) - len(modified) - len(removed)}


def _data_paths(data_dir: Path) -> dict[str, Path]:
    data_dir = Path(data_dir)
    return {
        "msg_index": data_dir / "msg_index.jsonl",
        "bursts": data_dir / "bursts.jsonl",
        "chunks": data_dir / "chunks.jsonl",
        "arcs": data_dir / "arcs.jsonl",
        "manifest": data_dir / "manifest.json",
        "tagging_todo": data_dir / "tagging.todo.jsonl",
        "tagging_done": data_dir / "tagging.done.jsonl",
    }


def run_ingest_plan(*, source_path: Path, data_dir: Path,
                    burst_threshold_min: int,
                    tagging_description: str = "",
                    tagging_seed_tags: list[str] | None = None,
                    me_real_names: list[str] | None = None,
                    me_name: str = "") -> dict:
    """Build msg_index + bursts, emit tagging todos. No LLM, no arcs yet.

    Idempotent: re-emitting todos for the same burst content is a no-op.

    `me_real_names` + `me_name` configure the operator-identity scrubber. When
    `me_real_names` is non-empty, occurrences of those patterns in message
    bodies and quotes are replaced with `me_name` (or its first token, for
    single-token patterns) before anything is written under `data_dir`.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    p = _data_paths(data_dir)

    scrub = compile_scrubber(me_real_names or [], me_name)

    source = _load_raw(source_path)
    diff = diff_messages(source, p["msg_index"])
    build_msg_index(source, p["msg_index"], scrub=scrub)
    msgs = load_msg_index(p["msg_index"])
    bursts = detect_bursts(msgs, threshold_min=burst_threshold_min)
    write_bursts(bursts, p["bursts"])

    manifest = Manifest.load_or_init(p["manifest"], burst_threshold_min=burst_threshold_min)
    cache_by_id = load_chunks_as_cache(p["chunks"], manifest.content_hashes)

    new_hashes = emit_tagging_todos(
        bursts, msgs, cache_by_id, p["tagging_todo"],
        description=tagging_description, seed_tags=tagging_seed_tags,
    )
    # Persist hashes early so finalize can still recognize cache hits if the
    # process is interrupted between plan and finalize.
    manifest.last_processed_msg_ts = msgs[-1]["date"] if msgs else None
    manifest.burst_count = len(bursts)
    manifest.content_hashes = new_hashes
    manifest.save(p["manifest"])

    todos = sum(1 for _ in p["tagging_todo"].open(encoding="utf-8")) if p["tagging_todo"].exists() else 0
    return {
        "diff": {k: len(v) if isinstance(v, list) else v for k, v in diff.items()},
        "bursts": len(bursts),
        "tagging_todos": todos,
    }


def run_ingest_finalize(*, data_dir: Path,
                        min_burst_count: int, min_msg_count: int) -> dict:
    """Read tagging done, write chunks, detect arcs, update manifest. No LLM."""
    data_dir = Path(data_dir)
    p = _data_paths(data_dir)

    bursts = [json.loads(l) for l in p["bursts"].read_text(encoding="utf-8").splitlines() if l.strip()]
    manifest = Manifest.load_or_init(p["manifest"], burst_threshold_min=0)
    cache_by_id = load_chunks_as_cache(p["chunks"], manifest.content_hashes)

    tagging_stats = finalize_tagging(
        bursts, cache_by_id, p["tagging_todo"], p["tagging_done"], p["chunks"],
    )

    chunks = [json.loads(l) for l in p["chunks"].read_text(encoding="utf-8").splitlines() if l.strip()]
    arcs = detect_arcs(bursts, chunks, min_burst_count=min_burst_count, min_msg_count=min_msg_count)
    write_arcs(arcs, p["arcs"])

    manifest.burst_count = len(bursts)
    manifest.save(p["manifest"])
    return {"tagging": tagging_stats, "bursts": len(bursts), "arcs": len(arcs)}

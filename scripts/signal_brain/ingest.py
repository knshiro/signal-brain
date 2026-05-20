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
from signal_brain.taxonomy import (
    emit_taxonomy_todo,
    finalize_taxonomy,
    load_taxonomy_cache,
    source_content_hash,
)
from signal_brain.worklist import load_done, load_todo


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
        "taxonomy_todo": data_dir / "taxonomy.todo.jsonl",
        "taxonomy_done": data_dir / "taxonomy.done.jsonl",
        "taxonomy_cache": data_dir / "taxonomy.json",
    }


def run_ingest_plan(*, source_path: Path, data_dir: Path,
                    burst_threshold_min: int,
                    tagging_description: str = "",
                    tagging_seed_tags: list[str] | None = None,
                    me_real_names: list[str] | None = None,
                    me_name: str = "") -> dict:
    """Build msg_index + bursts, then either emit a taxonomy todo or tagging todos.

    Self-progressing: first call (no taxonomy cache) emits only the taxonomy
    todo and returns `taxonomy_pending=True`. Second call (after the agent has
    produced taxonomy.done) loads the taxonomy, emits tagging todos with it
    injected as required vocabulary, returns `taxonomy_pending=False`.

    Idempotent at both layers: re-emitting todos for the same burst content
    (or the same taxonomy job) is a no-op.

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

    diff_summary = {k: len(v) if isinstance(v, list) else v for k, v in diff.items()}

    # Stage 1: taxonomy.
    src_hash = source_content_hash(msgs)
    taxonomy_cache = load_taxonomy_cache(p["taxonomy_cache"], source_hash=src_hash)
    if taxonomy_cache is None:
        # Try to finalize from an existing done file (the orchestrator may have
        # just produced it); otherwise emit the todo and return early.
        #
        # taxonomy.json is a content-hash-keyed cache, not an LLM deliverable —
        # it is phase-agnostic by design. finalize_taxonomy is idempotent, so
        # writing the cache here (from --plan, to self-progress) is intentional,
        # not a plan/finalize layering leak. run_ingest_finalize writes it too.
        finalized = finalize_taxonomy(
            p["taxonomy_todo"], p["taxonomy_done"], p["taxonomy_cache"],
            source_hash=src_hash,
        )
        if finalized is not None:
            # finalize_taxonomy returns the same dict shape as load_taxonomy_cache.
            taxonomy_cache = finalized
        else:
            emit_taxonomy_todo(
                msgs, p["taxonomy_todo"],
                description=tagging_description, source_hash=src_hash,
            )
            todos = sum(1 for _ in p["taxonomy_todo"].open(encoding="utf-8"))
            return {
                "diff": diff_summary,
                "bursts": len(bursts),
                "taxonomy_pending": True,
                "taxonomy_todos": todos,
                "tagging_todos": 0,
            }

    taxonomy = taxonomy_cache["taxonomy"]

    # Stage 2: tagging with taxonomy in hand.
    manifest = Manifest.load_or_init(p["manifest"], burst_threshold_min=burst_threshold_min)
    cache_by_id = load_chunks_as_cache(p["chunks"], manifest.content_hashes)

    taxonomy_hash = source_content_hash([
        {"msg_id": "__taxonomy__", "body": json.dumps(taxonomy, sort_keys=True),
         "reactions": []}
    ])

    new_hashes = emit_tagging_todos(
        bursts, msgs, cache_by_id, p["tagging_todo"],
        description=tagging_description,
        seed_tags=tagging_seed_tags,
        required_taxonomy=taxonomy,
        taxonomy_hash=taxonomy_hash,
    )
    # Persist hashes early so finalize can still recognize cache hits if the
    # process is interrupted between plan and finalize.
    manifest.last_processed_msg_ts = msgs[-1]["date"] if msgs else None
    manifest.burst_count = len(bursts)
    manifest.content_hashes = new_hashes
    manifest.save(p["manifest"])

    # Report work remaining, not file size: tagging.todo.jsonl is append-only,
    # so a re-run of --plan after a completed --finalize must show 0, not the
    # full count. Count todo job_ids that have no matching done row.
    todo_jobs = {r["job_id"] for r in load_todo(p["tagging_todo"])}
    done_jobs = set(load_done(p["tagging_done"]).keys())
    tagging_todos = len(todo_jobs - done_jobs)
    return {
        "diff": diff_summary,
        "bursts": len(bursts),
        "taxonomy_pending": False,
        "taxonomy_todos": 0,
        "tagging_todos": tagging_todos,
    }


def run_ingest_finalize(*, data_dir: Path,
                        min_burst_count: int, min_msg_count: int) -> dict:
    """Read tagging done, write chunks, detect arcs, update manifest. No LLM."""
    data_dir = Path(data_dir)
    p = _data_paths(data_dir)

    # Finalize the taxonomy stage too: a caller may run --finalize after
    # producing taxonomy.done out-of-band. Idempotent, and a no-op when there
    # is no matching done row.
    msgs = load_msg_index(p["msg_index"])
    src_hash = source_content_hash(msgs)
    finalize_taxonomy(
        p["taxonomy_todo"], p["taxonomy_done"], p["taxonomy_cache"],
        source_hash=src_hash,
    )

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

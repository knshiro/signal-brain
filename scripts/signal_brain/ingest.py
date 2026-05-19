"""Incremental ingest pipeline."""
from __future__ import annotations
import json
from pathlib import Path
from signal_brain.msg_index import build_msg_index, load_msg_index, msg_id
from signal_brain.bursts import detect_bursts, burst_content_hash, write_bursts
from signal_brain.tagging import tag_bursts
from signal_brain.arcs import detect_arcs, write_arcs
from signal_brain.manifest import Manifest


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


def run_ingest_data_layer(*, source_path: Path, data_dir: Path, llm,
                          burst_threshold_min: int, min_burst_count: int,
                          min_msg_count: int,
                          tagging_description: str = "",
                          tagging_seed_tags: list[str] | None = None) -> dict:
    """Builds msg_index → bursts → chunks → arcs → manifest. Returns stats."""
    source = _load_raw(source_path)
    data_dir = Path(data_dir)
    data_dir.mkdir(exist_ok=True)
    msg_index_path = data_dir / "msg_index.jsonl"
    chunks_path = data_dir / "chunks.jsonl"
    bursts_path = data_dir / "bursts.jsonl"
    arcs_path = data_dir / "arcs.jsonl"
    manifest_path = data_dir / "manifest.json"

    diff = diff_messages(source, msg_index_path)
    build_msg_index(source, msg_index_path)
    msgs = load_msg_index(msg_index_path)
    bursts = detect_bursts(msgs, threshold_min=burst_threshold_min)
    write_bursts(bursts, bursts_path)

    manifest = Manifest.load_or_init(manifest_path, burst_threshold_min=burst_threshold_min)
    # Build cache_by_id from previous chunks + previous hashes
    cache_by_id: dict[str, dict] = {}
    if chunks_path.exists():
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            cache_by_id[r["burst_id"]] = {
                "hash": manifest.content_hashes.get(r["burst_id"], ""),
                "topics": r["topics"], "primary": r["primary"], "summary": r["summary"],
            }
    new_hashes = tag_bursts(
        bursts, msgs, llm, cache_by_id, chunks_path,
        description=tagging_description,
        seed_tags=tagging_seed_tags,
    )
    chunks = [json.loads(l) for l in chunks_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    arcs = detect_arcs(bursts, chunks, min_burst_count=min_burst_count, min_msg_count=min_msg_count)
    write_arcs(arcs, arcs_path)

    manifest.last_processed_msg_ts = msgs[-1]["date"] if msgs else None
    manifest.burst_count = len(bursts)
    manifest.content_hashes = new_hashes
    manifest.save(manifest_path)

    return {"diff": {k: len(v) if isinstance(v, list) else v for k, v in diff.items()},
            "bursts": len(bursts), "arcs": len(arcs)}

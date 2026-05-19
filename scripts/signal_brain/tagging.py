"""L2a: per-burst topic tagging via the plan/finalize worklist contract.

Plan phase (`emit_tagging_todos`): for each burst whose content hash differs
from the cache, append a row to `tagging.todo.jsonl`. No LLM is called.

Finalize phase (`finalize_tagging`): read `tagging.done.jsonl`, merge with
cache for unchanged bursts, write `chunks.jsonl`. Still no LLM.

The agent (Claude Code or Codex) sits between the two phases, dispatching one
subagent per todo row to produce the JSON response.
"""
from __future__ import annotations

import json
from pathlib import Path

from signal_brain.bursts import burst_content_hash
from signal_brain.worklist import (
    WorklistError,
    emit,
    load_done,
    load_todo,
    validate_response,
)


TAGGING_RESPONSE_SCHEMA = {
    "required": ["topics", "primary", "summary"],
    "types": {"topics": "list", "primary": "str", "summary": "str"},
}


def build_system_prompt(description: str = "") -> str:
    """System prompt for the tagger. `description` is an optional context hint."""
    context = f"\n\nContext: {description}." if description.strip() else ""
    return (
        "You are a topic tagger for a Signal conversation between two people. "
        "Tag each burst with 1-3 topics." + context + "\n\n"
        "Rules:\n"
        "- Output VALID JSON. No prose around it.\n"
        "- Output language: English (lowercase, kebab-case slugs).\n"
        "- Quotes in summaries must preserve the original source language.\n"
        "- \"primary\" is the single dominant topic.\n"
        "- \"summary\" is one sentence (<= 25 words) describing what was discussed, in English.\n"
    )


def build_user_prompt(burst_id: str, start: str, messages: str,
                     seed_tags: list[str] | None) -> str:
    """User prompt for a single burst. `seed_tags` is optional; empty means no priming."""
    seed_section = ""
    if seed_tags:
        seed_section = (
            "Seed tags (use when they fit; you may propose new ones if needed):\n"
            f"{', '.join(seed_tags)}\n\n"
        )
    return (
        f"{seed_section}"
        f"Burst {burst_id} ({start}):\n"
        f"---\n{messages}\n---\n\n"
        'Output JSON:\n{"topics": ["...", "..."], "primary": "...", "summary": "..."}'
    )


def _render_burst_for_tagging(burst: dict, all_messages: list[dict]) -> str:
    by_id = {m["msg_id"]: m for m in all_messages}
    lines = []
    for mid in burst["msg_ids"]:
        m = by_id.get(mid)
        if not m:
            continue
        body = (m.get("body") or "").strip().replace("\n", " ")
        if body:
            lines.append(f"{m['sender']}: {body}")
    return "\n".join(lines)


def emit_tagging_todos(
    bursts: list[dict],
    all_messages: list[dict],
    cache_by_id: dict[str, dict],
    todo_path: Path,
    *,
    description: str = "",
    seed_tags: list[str] | None = None,
) -> dict[str, str]:
    """Plan phase: for each cache-miss burst, append a todo row.

    Returns a `{burst_id: content_hash}` map so the caller can persist it in the
    manifest. The hash is computed for every burst (cache hit or miss) so the
    manifest reflects the post-run state.
    """
    system_prompt = build_system_prompt(description)
    new_hashes: dict[str, str] = {}
    for b in bursts:
        h = burst_content_hash(b, all_messages)
        new_hashes[b["id"]] = h
        cached = cache_by_id.get(b["id"])
        if cached and cached.get("hash") == h:
            continue
        user = build_user_prompt(
            burst_id=b["id"], start=b["start"],
            messages=_render_burst_for_tagging(b, all_messages),
            seed_tags=seed_tags,
        )
        emit(
            todo_path,
            stage="tagging",
            kind="burst",
            system=system_prompt,
            user=user,
            response_schema=TAGGING_RESPONSE_SCHEMA,
            context={"burst_id": b["id"], "content_hash": h},
        )
    return new_hashes


def finalize_tagging(
    bursts: list[dict],
    cache_by_id: dict[str, dict],
    todo_path: Path,
    done_path: Path,
    chunks_path: Path,
) -> dict:
    """Read done rows, merge with cache, write chunks.jsonl in burst order.

    Returns stats::

        {"new": int, "cached": int, "missing": [burst_id, ...], "invalid": [burst_id, ...]}

    `missing` is non-empty when the agent failed to produce a response for a
    todo row (the orchestrator surfaces this and offers a retry). `invalid` is
    when the response existed but failed schema validation.
    """
    todos_by_job = {row["job_id"]: row for row in load_todo(todo_path)}
    done_by_job = load_done(done_path)

    out_rows: list[dict] = []
    missing: list[str] = []
    invalid: list[str] = []
    new = 0
    cached = 0
    for b in bursts:
        bid = b["id"]
        prior = cache_by_id.get(bid)
        # Find the most recent todo for this burst (matched by context.burst_id).
        todo = next(
            (t for t in todos_by_job.values() if t["context"].get("burst_id") == bid),
            None,
        )
        if todo is None:
            # No todo emitted — cache hit. Reuse prior chunk if present.
            if prior is None:
                missing.append(bid)
                continue
            out_rows.append({
                "burst_id": bid, "topics": prior["topics"],
                "primary": prior["primary"], "summary": prior["summary"],
            })
            cached += 1
            continue
        done = done_by_job.get(todo["job_id"])
        if done is None:
            missing.append(bid)
            continue
        resp = done.get("response", {})
        try:
            validate_response(resp, todo["response_schema"])
        except WorklistError:
            invalid.append(bid)
            continue
        out_rows.append({
            "burst_id": bid, "topics": resp["topics"],
            "primary": resp["primary"], "summary": resp["summary"],
        })
        new += 1

    Path(chunks_path).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + ("\n" if out_rows else ""),
        encoding="utf-8",
    )
    return {"new": new, "cached": cached, "missing": missing, "invalid": invalid}


def load_chunks_as_cache(chunks_path: Path, hashes_by_id: dict[str, str]) -> dict[str, dict]:
    """Read an existing chunks.jsonl into a {burst_id: {hash, topics, primary, summary}} map.

    The hash is looked up from the manifest's stored hashes_by_id, since chunks.jsonl
    doesn't carry the hash itself.
    """
    if not Path(chunks_path).exists():
        return {}
    cache: dict[str, dict] = {}
    for line in Path(chunks_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cache[row["burst_id"]] = {
            "hash": hashes_by_id.get(row["burst_id"], ""),
            "topics": row["topics"], "primary": row["primary"], "summary": row["summary"],
        }
    return cache

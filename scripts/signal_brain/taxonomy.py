"""L1.5: canonical-vocabulary extraction via the plan/finalize worklist contract.

Plan phase (`emit_taxonomy_todo`): one todo row per ingest run with the full
conversation embedded. No LLM is called.

Finalize phase (`finalize_taxonomy`): read `taxonomy.done.jsonl`, write
`taxonomy.json` keyed by the source content hash. Still no LLM.

The agent (Claude Code or Codex) sits between, dispatching a single subagent for
the one todo row. Per-burst tagging in `tagging.py` reads `taxonomy.json` and
uses it as required vocabulary.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from signal_brain.worklist import (
    WorklistError,
    emit,
    load_done,
    load_todo,
    validate_response,
)


TAXONOMY_RESPONSE_SCHEMA = {
    "required": ["taxonomy", "concepts", "notes"],
    "types": {"taxonomy": "list", "concepts": "list", "notes": "str"},
}


def source_content_hash(messages: list[dict]) -> str:
    """SHA1 over (msg_id, body, reactions) for every message. Stable across runs."""
    h = hashlib.sha1()
    for m in messages:
        h.update(m["msg_id"].encode("utf-8"))
        h.update(b"\x00")
        h.update(m.get("body", "").encode("utf-8"))
        h.update(b"\x00")
        h.update(json.dumps(m.get("reactions", []), sort_keys=True).encode("utf-8"))
        h.update(b"\x01")
    return f"sha1:{h.hexdigest()}"


def build_system_prompt(description: str = "") -> str:
    """System prompt for the taxonomy extractor."""
    context = f"\n\nContext: {description}." if description.strip() else ""
    return (
        "You are a vocabulary curator for a Signal conversation between two people. "
        "Read the whole conversation and produce two things: a `taxonomy` of topic "
        "slugs covering its recurring themes, and a `concepts` subset naming the "
        "themes substantial enough to deserve their own wiki page." + context + "\n\n"
        "Rules:\n"
        "- Output VALID JSON. No prose around it.\n"
        "- Slugs are lowercase kebab-case English (even when the conversation is not in English).\n"
        "- TOPIC GRANULARITY: each `taxonomy` slug must be broad enough to recur across\n"
        "  the conversation. Merge facets of one theme into a single umbrella slug — do\n"
        "  NOT fragment a theme into siblings. For example, home renovation,\n"
        "  choosing contractors, and remodel budgeting are facets of ONE topic\n"
        "  (e.g. \"home-renovation\"), not three. Aim for roughly 10-18 topics; if you\n"
        "  pass ~20 you are fragmenting and should consolidate.\n"
        "- `concepts` is the subset of `taxonomy` slugs that are substantial themes the\n"
        "  two people develop arguments about — not incidental logistics, greetings, or\n"
        "  one-off banter. Every entry of `concepts` MUST also appear in `taxonomy`.\n"
        "- `notes` is one or two sentences summarising the taxonomy.\n"
    )


def build_user_prompt(messages_text: str) -> str:
    """User prompt embedding the full conversation as a single text blob."""
    return (
        "Conversation (chronological):\n"
        "---\n"
        f"{messages_text}\n"
        "---\n\n"
        'Output JSON:\n'
        '{"taxonomy": ["slug-1", "slug-2", "..."], '
        '"concepts": ["slug-1", "..."], "notes": "..."}'
    )


def _render_full_conversation(messages: list[dict]) -> str:
    lines: list[str] = []
    for m in messages:
        body = (m.get("body") or "").strip().replace("\n", " ")
        if not body:
            continue
        sender = m.get("sender", "?")
        lines.append(f"{sender}: {body}")
    return "\n".join(lines)


def emit_taxonomy_todo(
    messages: list[dict],
    todo_path: Path,
    *,
    description: str,
    source_hash: str,
) -> str:
    """Plan phase: emit one taxonomy todo row. Idempotent by job_id.

    Returns the job_id.
    """
    system = build_system_prompt(description)
    user = build_user_prompt(_render_full_conversation(messages))
    return emit(
        todo_path,
        stage="taxonomy",
        kind="source",
        system=system,
        user=user,
        response_schema=TAXONOMY_RESPONSE_SCHEMA,
        context={"source_hash": source_hash},
    )


def finalize_taxonomy(
    todo_path: Path,
    done_path: Path,
    cache_path: Path,
    *,
    source_hash: str,
) -> dict | None:
    """Read the done row matching the source_hash, write the cache file.

    Returns the parsed `{"source_hash", "taxonomy", "concepts", "notes"}` dict
    or None if no done row exists yet (caller treats that as "taxonomy still
    pending").

    An empty taxonomy list is rejected as malformed input: it returns None
    (same as a missing/failing done row) and no cache file is written, so the
    orchestrator re-dispatches the taxonomy subagent. An empty `concepts` list
    is allowed (a conversation with no page-worthy theme is valid, just rare).
    Any `concepts` slug not present in `taxonomy` is dropped defensively.
    """
    todos = {row["job_id"]: row for row in load_todo(todo_path)}
    todo = next(
        (t for t in todos.values() if t["context"].get("source_hash") == source_hash),
        None,
    )
    if todo is None:
        return None
    done = load_done(done_path).get(todo["job_id"])
    if done is None:
        return None
    resp = done.get("response", {})
    try:
        validate_response(resp, todo["response_schema"])
    except WorklistError:
        return None
    # An empty taxonomy passes the schema (it only checks `list`) but is
    # useless: it would flow through as a falsy required_taxonomy and silently
    # disable controlled-vocabulary tagging. Treat it as still-pending.
    if not resp["taxonomy"]:
        return None
    taxonomy_list = resp["taxonomy"]
    taxonomy_set = set(taxonomy_list)
    concepts = [c for c in resp["concepts"] if c in taxonomy_set]
    cache_data = {
        "source_hash": source_hash,
        "taxonomy": taxonomy_list,
        "concepts": concepts,
        "notes": resp["notes"],
    }
    Path(cache_path).write_text(
        json.dumps(cache_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cache_data


def load_taxonomy_cache(cache_path: Path, *, source_hash: str) -> dict | None:
    """Return the full cached taxonomy dict if `source_hash` matches. None otherwise.

    The dict has the shape `{"source_hash", "taxonomy", "concepts", "notes"}`.
    Callers read `taxonomy` (tagging vocabulary) or `concepts` (page selection).

    A cached *empty* taxonomy is not a usable cache and returns None, so the
    caller falls through to (re-)dispatching the taxonomy stage. A cache written
    by an older finalize that predates `concepts` is tolerated: `concepts` is
    defaulted to an empty list so stale caches don't crash callers.
    """
    cache_path = Path(cache_path)
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if data.get("source_hash") != source_hash:
        return None
    taxonomy = data.get("taxonomy")
    if not isinstance(taxonomy, list) or not taxonomy:
        return None
    data.setdefault("concepts", [])
    return data

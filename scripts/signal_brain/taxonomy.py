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
    "required": ["taxonomy", "notes"],
    "types": {"taxonomy": "list", "notes": "str"},
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
        "Your job is to extract a small, canonical taxonomy of topic slugs that "
        "describe the recurring themes of the whole conversation." + context + "\n\n"
        "Rules:\n"
        "- Output VALID JSON. No prose around it.\n"
        "- Output language: English (lowercase, kebab-case slugs).\n"
        "- Aim for 10-25 slugs, choosing the granularity that best canonicalises\n"
        "  recurring themes. Too few collapses distinct topics; too many fragments\n"
        "  shared themes into unique ones.\n"
        "- Prefer compound slugs that name concrete themes (e.g.\n"
        "  \"home-renovation\", \"book-recommendations\") over generic single words\n"
        "  (e.g. \"money\", \"news\").\n"
        "- The `notes` field is one or two sentences summarising the taxonomy.\n"
    )


def build_user_prompt(messages_text: str) -> str:
    """User prompt embedding the full conversation as a single text blob."""
    return (
        "Conversation (chronological):\n"
        "---\n"
        f"{messages_text}\n"
        "---\n\n"
        'Output JSON:\n{"taxonomy": ["slug-1", "slug-2", "..."], "notes": "..."}'
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

    Returns the parsed `{"taxonomy": [...], "notes": "..."}` or None if no done
    row exists yet (caller treats that as "taxonomy still pending").

    An empty taxonomy list is rejected as malformed input: it returns None
    (same as a missing/failing done row) and no cache file is written, so the
    orchestrator re-dispatches the taxonomy subagent.
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
    cache_data = {
        "source_hash": source_hash,
        "taxonomy": resp["taxonomy"],
        "notes": resp["notes"],
    }
    Path(cache_path).write_text(
        json.dumps(cache_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cache_data


def load_taxonomy_cache(cache_path: Path, *, source_hash: str) -> list[str] | None:
    """Return the cached taxonomy slugs if `source_hash` matches. None otherwise.

    A cached *empty* taxonomy is not a usable cache and returns None, so the
    caller falls through to (re-)dispatching the taxonomy stage.
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
    return taxonomy

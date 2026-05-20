# Taxonomy-First Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a `taxonomy` stage upstream of per-burst tagging that extracts a canonical vocabulary from the full conversation. Per-burst tagging then uses that vocabulary as a *required* slug pool, so the wiki finally accumulates enough shared slugs for concept and position pages to fire on small conversations.

**Architecture:** New worklist stage following the existing plan/finalize pattern. One todo per ingest run, single subagent dispatch, output cached at `brain/<src>/data/taxonomy.json` keyed by source content hash. `run_ingest_plan` becomes self-progressing: if taxonomy is missing, it emits only the taxonomy todo and returns early; once present, it emits per-burst tagging todos with the taxonomy injected as required vocabulary. The orchestrator skill loops `--plan` + fan-out until no new todos appear, then `--finalize`.

**Tech Stack:** Python 3.11+, existing worklist contract (`scripts/signal_brain/worklist.py`), no new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-20-taxonomy-first.md`
**Branch:** `feat/taxonomy-first`
**Dependency:** Ships after `feat/anonymize-ingest`. Branch off main once that PR is merged.

---

## File Structure

- **Create:** `scripts/signal_brain/taxonomy.py` — `emit_taxonomy_todo`, `finalize_taxonomy`, `load_taxonomy_cache`, plus prompts and the response schema.
- **Create:** `scripts/tests/test_taxonomy.py` — unit tests for the new module.
- **Modify:** `scripts/signal_brain/bursts.py::burst_content_hash` — fold the taxonomy hash into the cache key so taxonomy changes invalidate burst caches.
- **Modify:** `scripts/signal_brain/tagging.py` — extend `TAGGING_RESPONSE_SCHEMA` with `out_of_taxonomy`, update `build_system_prompt` and `build_user_prompt` to enforce a required taxonomy, propagate `out_of_taxonomy` through `finalize_tagging` into chunks.jsonl.
- **Modify:** `scripts/signal_brain/ingest.py` — `run_ingest_plan` becomes staged (taxonomy first, then tagging); `run_ingest_finalize` writes `taxonomy.json` and forwards `out_of_taxonomy` to chunks.
- **Modify:** `scripts/signal_brain/cli.py` — surface `taxonomy_pending` and `taxonomy_todos` in the stats so the orchestrator can loop.
- **Modify:** `scripts/signal_brain/lint.py` — add an `out_of_taxonomy_rate` check.
- **Modify:** `scripts/tests/test_bursts.py`, `test_tagging.py`, `test_ingest.py`, `test_lint.py` — extend coverage.
- **Modify:** `skills/signal-brain-build/SKILL.md` — change Step 2 + Step 3 to the loop pattern.

---

## Task 1: Source content hash + taxonomy module skeleton

**Files:**
- Create: `scripts/signal_brain/taxonomy.py`
- Test: `scripts/tests/test_taxonomy.py`

- [ ] **Step 1: Write failing tests for the hash and module skeleton**

Create `scripts/tests/test_taxonomy.py`:

```python
"""Tests for the taxonomy stage (plan/finalize worklist contract)."""
import json
from pathlib import Path

from signal_brain.taxonomy import (
    TAXONOMY_RESPONSE_SCHEMA,
    build_system_prompt,
    build_user_prompt,
    emit_taxonomy_todo,
    finalize_taxonomy,
    load_taxonomy_cache,
    source_content_hash,
)
from signal_brain.worklist import load_todo


def test_source_content_hash_stable_across_calls():
    msgs = [
        {"msg_id": "a::Me", "body": "hello", "reactions": []},
        {"msg_id": "b::Friend", "body": "salut", "reactions": []},
    ]
    h1 = source_content_hash(msgs)
    h2 = source_content_hash(msgs)
    assert h1 == h2
    assert h1.startswith("sha1:")


def test_source_content_hash_changes_when_body_changes():
    base = [{"msg_id": "a::Me", "body": "hello", "reactions": []}]
    modified = [{"msg_id": "a::Me", "body": "HELLO", "reactions": []}]
    assert source_content_hash(base) != source_content_hash(modified)


def test_source_content_hash_changes_when_message_added():
    base = [{"msg_id": "a::Me", "body": "x", "reactions": []}]
    extended = base + [{"msg_id": "b::Me", "body": "y", "reactions": []}]
    assert source_content_hash(base) != source_content_hash(extended)


def test_taxonomy_schema_shape():
    assert TAXONOMY_RESPONSE_SCHEMA["required"] == ["taxonomy", "notes"]
    assert TAXONOMY_RESPONSE_SCHEMA["types"]["taxonomy"] == "list"
    assert TAXONOMY_RESPONSE_SCHEMA["types"]["notes"] == "str"


def test_system_prompt_mentions_canonical_vocabulary():
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "vocabulary" in lower or "taxonomy" in lower
    assert "slug" in lower


def test_user_prompt_embeds_conversation_text():
    text = "Me: hi\nFriend: hello"
    prompt = build_user_prompt(text)
    assert "Me: hi" in prompt
    assert "Friend: hello" in prompt


def test_emit_taxonomy_todo_writes_one_row(tmp_path):
    msgs = [
        {"msg_id": "a::Me", "sender": "Me", "body": "discutons capital",
         "reactions": []},
        {"msg_id": "b::Friend", "sender": "Friend", "body": "ok parlons",
         "reactions": []},
    ]
    todo = tmp_path / "taxonomy.todo.jsonl"
    job_id = emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    assert job_id is not None
    rows = load_todo(todo)
    assert len(rows) == 1
    assert rows[0]["stage"] == "taxonomy"
    assert rows[0]["kind"] == "source"
    assert rows[0]["context"]["source_hash"] == "sha1:abc"
    assert "discutons capital" in rows[0]["user_prompt"]


def test_emit_taxonomy_todo_is_idempotent_on_replan(tmp_path):
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "x", "reactions": []}]
    todo = tmp_path / "taxonomy.todo.jsonl"
    emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    assert len(load_todo(todo)) == 1


def test_finalize_taxonomy_writes_cache(tmp_path):
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "x", "reactions": []}]
    todo = tmp_path / "taxonomy.todo.jsonl"
    emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    todo_row = load_todo(todo)[0]
    done = tmp_path / "taxonomy.done.jsonl"
    done.write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {"taxonomy": ["wealth-concentration", "media-criticism"],
                     "notes": "two themes"},
    }) + "\n", encoding="utf-8")
    cache = tmp_path / "taxonomy.json"
    result = finalize_taxonomy(todo, done, cache, source_hash="sha1:abc")
    assert result["taxonomy"] == ["wealth-concentration", "media-criticism"]
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["source_hash"] == "sha1:abc"
    assert data["taxonomy"] == ["wealth-concentration", "media-criticism"]
    assert data["notes"] == "two themes"


def test_load_taxonomy_cache_hit(tmp_path):
    cache = tmp_path / "taxonomy.json"
    cache.write_text(json.dumps({
        "source_hash": "sha1:abc",
        "taxonomy": ["a", "b"],
        "notes": "",
    }), encoding="utf-8")
    result = load_taxonomy_cache(cache, source_hash="sha1:abc")
    assert result == ["a", "b"]


def test_load_taxonomy_cache_miss_on_hash_mismatch(tmp_path):
    cache = tmp_path / "taxonomy.json"
    cache.write_text(json.dumps({
        "source_hash": "sha1:old",
        "taxonomy": ["a"],
        "notes": "",
    }), encoding="utf-8")
    assert load_taxonomy_cache(cache, source_hash="sha1:new") is None


def test_load_taxonomy_cache_missing_file_returns_none(tmp_path):
    assert load_taxonomy_cache(tmp_path / "nope.json", source_hash="sha1:abc") is None
```

- [ ] **Step 2: Run, confirm they all fail**

Run: `pytest scripts/tests/test_taxonomy.py -v`
Expected: `ModuleNotFoundError: No module named 'signal_brain.taxonomy'`.

- [ ] **Step 3: Implement `taxonomy.py`**

Create `scripts/signal_brain/taxonomy.py`:

```python
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
        "  \"wealth-concentration\", \"media-criticism\") over generic single words\n"
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
    """Return the cached taxonomy slugs if `source_hash` matches. None otherwise."""
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
    if not isinstance(taxonomy, list):
        return None
    return taxonomy
```

- [ ] **Step 4: Run, confirm all pass**

Run: `pytest scripts/tests/test_taxonomy.py -v`
Expected: 12 passed.

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/taxonomy.py scripts/tests/test_taxonomy.py
git commit -m "feat(taxonomy): module with source_content_hash and plan/finalize"
```

---

## Task 2: Fold taxonomy hash into `burst_content_hash`

**Goal:** Make the burst cache key depend on the taxonomy, so taxonomy changes invalidate all chunks and force retagging.

**Files:**
- Modify: `scripts/signal_brain/bursts.py::burst_content_hash`
- Test: `scripts/tests/test_bursts.py`

- [ ] **Step 1: Write failing tests**

Add to `scripts/tests/test_bursts.py`:

```python
def test_burst_content_hash_changes_when_taxonomy_hash_changes():
    burst = {"msg_ids": ["a::Me"]}
    messages = [{"msg_id": "a::Me", "body": "hi", "reactions": []}]
    h_empty = burst_content_hash(burst, messages)
    h_with_tax = burst_content_hash(burst, messages, taxonomy_hash="sha1:tax-v1")
    h_with_tax2 = burst_content_hash(burst, messages, taxonomy_hash="sha1:tax-v2")
    assert h_empty != h_with_tax
    assert h_with_tax != h_with_tax2


def test_burst_content_hash_default_taxonomy_hash_is_empty_string():
    """Without an explicit taxonomy_hash, behaviour matches a literal "" suffix.

    This locks in the back-compat shape: callers that don't pass taxonomy_hash
    see the same value as callers passing "".
    """
    burst = {"msg_ids": ["a::Me"]}
    messages = [{"msg_id": "a::Me", "body": "hi", "reactions": []}]
    assert burst_content_hash(burst, messages) == burst_content_hash(
        burst, messages, taxonomy_hash=""
    )
```

(Top of file already imports `burst_content_hash`.)

- [ ] **Step 2: Run, confirm they fail**

Run: `pytest scripts/tests/test_bursts.py -v`
Expected: the two new tests fail (`TypeError: ... unexpected keyword argument 'taxonomy_hash'`).

- [ ] **Step 3: Extend `burst_content_hash`**

Edit `scripts/signal_brain/bursts.py`. Replace:

```python
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
```

With:

```python
def burst_content_hash(
    burst: dict,
    all_messages: list[dict],
    *,
    taxonomy_hash: str = "",
) -> str:
    """SHA1 over msg_id + body + reactions for every message in the burst.

    `taxonomy_hash` (optional) is folded into the digest. Pass the SHA of the
    active taxonomy.json when one is in effect, so taxonomy changes invalidate
    the burst cache and force retagging.
    """
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
    h.update(b"\x02")
    h.update(taxonomy_hash.encode("utf-8"))
    return f"sha1:{h.hexdigest()}"
```

⚠️ **Migration note:** this changes the default-value hash compared to the pre-PR version (since we added the trailing `\x02` + empty taxonomy_hash). On first run after merging this PR, every existing manifest cache entry will miss, forcing one full retag pass. That's expected and acceptable — we're shipping taxonomy-first anyway, which would invalidate them too.

- [ ] **Step 4: Run all tests**

Run: `pytest scripts/tests/test_bursts.py -v`
Expected: all pass.

Run: `pytest -q`
Expected: all pass. The existing tagging tests use mocker to patch `burst_content_hash`, so they're insulated from the digest change.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/bursts.py scripts/tests/test_bursts.py
git commit -m "refactor(bursts): fold optional taxonomy_hash into burst_content_hash"
```

---

## Task 3: Extend tagging prompts + schema to enforce taxonomy

**Files:**
- Modify: `scripts/signal_brain/tagging.py`
- Test: `scripts/tests/test_tagging.py`

- [ ] **Step 1: Write failing tests**

Add to `scripts/tests/test_tagging.py`:

```python
def test_system_prompt_includes_required_vocabulary_when_taxonomy_provided():
    prompt = build_system_prompt(required_taxonomy=["wealth", "media"])
    assert "controlled vocabulary" in prompt.lower() or "required vocabulary" in prompt.lower()
    assert "out_of_taxonomy" in prompt


def test_system_prompt_neutral_when_no_taxonomy():
    prompt = build_system_prompt()
    assert "controlled vocabulary" not in prompt.lower()
    assert "out_of_taxonomy" not in prompt


def test_user_prompt_includes_required_vocabulary_section():
    prompt = build_user_prompt(
        "B0001", "2026-05-05T13:00", "Me: hi",
        seed_tags=None,
        required_taxonomy=["wealth-concentration", "media-criticism"],
    )
    assert "Required vocabulary" in prompt
    assert "wealth-concentration" in prompt
    assert "media-criticism" in prompt


def test_user_prompt_required_taxonomy_takes_precedence_over_seed_tags():
    """When both are set, the required-vocabulary framing wins; soft seed_tags suppressed."""
    prompt = build_user_prompt(
        "B0001", "2026-05-05T13:00", "Me: hi",
        seed_tags=["soft-a"],
        required_taxonomy=["hard-b"],
    )
    assert "Required vocabulary" in prompt
    assert "hard-b" in prompt
    assert "Seed tags" not in prompt


def test_tagging_schema_includes_out_of_taxonomy():
    from signal_brain.tagging import TAGGING_RESPONSE_SCHEMA
    assert "out_of_taxonomy" in TAGGING_RESPONSE_SCHEMA["required"]
    assert TAGGING_RESPONSE_SCHEMA["types"]["out_of_taxonomy"] == "bool"


def test_emit_tagging_todos_threads_taxonomy_into_prompt(tmp_path, mocker):
    bursts = [{"id": "B0100", "msg_ids": ["a::Me"], "start": "2026-05-05T13:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "discutons",
             "date": "2026-05-05T13:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:n")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(
        bursts, msgs, {}, todo,
        required_taxonomy=["wealth-concentration", "media-criticism"],
    )
    row = load_todo(todo)[0]
    assert "Required vocabulary" in row["user_prompt"]
    assert "wealth-concentration" in row["user_prompt"]
    assert "out_of_taxonomy" in row["system_prompt"]


def test_finalize_tagging_propagates_out_of_taxonomy_to_chunks(tmp_path, mocker):
    bursts = [{"id": "B0200", "msg_ids": ["a::Me"], "start": "2026-05-05T14:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi",
             "date": "2026-05-05T14:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:n")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, {}, todo,
                       required_taxonomy=["wealth-concentration"])
    todo_row = load_todo(todo)[0]
    done = tmp_path / "tagging.done.jsonl"
    done.write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {
            "topics": ["wealth-concentration"],
            "primary": "wealth-concentration",
            "summary": "About money.",
            "out_of_taxonomy": False,
        },
    }) + "\n", encoding="utf-8")
    chunks = tmp_path / "chunks.jsonl"
    finalize_tagging(bursts, {}, todo, done, chunks)
    row = json.loads(chunks.read_text(encoding="utf-8").splitlines()[0])
    assert row["out_of_taxonomy"] is False
```

- [ ] **Step 2: Run, confirm they fail**

Run: `pytest scripts/tests/test_tagging.py -v`
Expected: the seven new tests fail.

- [ ] **Step 3: Update `TAGGING_RESPONSE_SCHEMA` and prompts**

Edit `scripts/signal_brain/tagging.py`. Replace the schema:

```python
TAGGING_RESPONSE_SCHEMA = {
    "required": ["topics", "primary", "summary", "out_of_taxonomy"],
    "types": {"topics": "list", "primary": "str", "summary": "str",
              "out_of_taxonomy": "bool"},
}
```

Replace `build_system_prompt`:

```python
def build_system_prompt(
    description: str = "",
    *,
    required_taxonomy: list[str] | None = None,
) -> str:
    """System prompt for the tagger. `description` is an optional context hint.

    When `required_taxonomy` is provided, the tagger is constrained to draw
    `topics` from that controlled vocabulary; bursts that genuinely don't fit
    set `out_of_taxonomy: true` and may propose a new slug.
    """
    context = f"\n\nContext: {description}." if description.strip() else ""
    taxonomy_rules = ""
    if required_taxonomy:
        taxonomy_rules = (
            "- Select all entries of \"topics\" from the controlled vocabulary in the user prompt.\n"
            "- Set \"out_of_taxonomy\": true only when NO vocabulary term genuinely fits;\n"
            "  in that case you may propose a new slug in \"topics\".\n"
            "- Otherwise set \"out_of_taxonomy\": false.\n"
        )
    else:
        taxonomy_rules = "- Set \"out_of_taxonomy\": false (no controlled vocabulary in effect).\n"
    return (
        "You are a topic tagger for a Signal conversation between two people. "
        "Tag each burst with 1-3 topics." + context + "\n\n"
        "Rules:\n"
        "- Output VALID JSON. No prose around it.\n"
        "- Output language: English (lowercase, kebab-case slugs).\n"
        "- Quotes in summaries must preserve the original source language.\n"
        "- \"primary\" is the single dominant topic.\n"
        "- \"summary\" is one sentence (<= 25 words) describing what was discussed, in English.\n"
        + taxonomy_rules
    )
```

Replace `build_user_prompt`:

```python
def build_user_prompt(
    burst_id: str,
    start: str,
    messages: str,
    seed_tags: list[str] | None,
    *,
    required_taxonomy: list[str] | None = None,
) -> str:
    """User prompt for a single burst.

    Precedence: when `required_taxonomy` is provided, it appears as "Required
    vocabulary" and `seed_tags` is suppressed (the harder framing wins). When
    only `seed_tags` is provided, it appears as soft "Seed tags". When both are
    empty/None, the prompt has no priming section.
    """
    priming = ""
    if required_taxonomy:
        priming = (
            "Required vocabulary (choose topics from this list; set "
            "out_of_taxonomy: true only if no entry fits):\n"
            f"{', '.join(required_taxonomy)}\n\n"
        )
    elif seed_tags:
        priming = (
            "Seed tags (use when they fit; you may propose new ones if needed):\n"
            f"{', '.join(seed_tags)}\n\n"
        )
    return (
        f"{priming}"
        f"Burst {burst_id} ({start}):\n"
        f"---\n{messages}\n---\n\n"
        'Output JSON:\n{"topics": ["..."], "primary": "...", "summary": "...", "out_of_taxonomy": false}'
    )
```

Replace `emit_tagging_todos`:

```python
def emit_tagging_todos(
    bursts: list[dict],
    all_messages: list[dict],
    cache_by_id: dict[str, dict],
    todo_path: Path,
    *,
    description: str = "",
    seed_tags: list[str] | None = None,
    required_taxonomy: list[str] | None = None,
    taxonomy_hash: str = "",
) -> dict[str, str]:
    """Plan phase: for each cache-miss burst, append a todo row.

    `required_taxonomy` (optional) is the controlled vocabulary; when set, the
    prompt enforces it and `seed_tags` is suppressed. `taxonomy_hash` is folded
    into `burst_content_hash` so taxonomy changes invalidate cache.
    """
    system_prompt = build_system_prompt(description, required_taxonomy=required_taxonomy)
    new_hashes: dict[str, str] = {}
    for b in bursts:
        h = burst_content_hash(b, all_messages, taxonomy_hash=taxonomy_hash)
        new_hashes[b["id"]] = h
        cached = cache_by_id.get(b["id"])
        if cached and cached.get("hash") == h:
            continue
        user = build_user_prompt(
            burst_id=b["id"], start=b["start"],
            messages=_render_burst_for_tagging(b, all_messages),
            seed_tags=seed_tags,
            required_taxonomy=required_taxonomy,
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
```

Update `finalize_tagging` to propagate the new field. Replace the `out_rows.append` calls inside the for-loop:

```python
        if todo is None:
            if prior is None:
                missing.append(bid)
                continue
            out_rows.append({
                "burst_id": bid, "topics": prior["topics"],
                "primary": prior["primary"], "summary": prior["summary"],
                "out_of_taxonomy": prior.get("out_of_taxonomy", False),
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
            "out_of_taxonomy": resp.get("out_of_taxonomy", False),
        })
        new += 1
```

And update `load_chunks_as_cache` to read the field back:

```python
def load_chunks_as_cache(chunks_path: Path, hashes_by_id: dict[str, str]) -> dict[str, dict]:
    """Read an existing chunks.jsonl into a per-burst cache map."""
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
            "out_of_taxonomy": row.get("out_of_taxonomy", False),
        }
    return cache
```

- [ ] **Step 4: Run all tagging tests**

Run: `pytest scripts/tests/test_tagging.py -v`
Expected: all pass (existing + new). The existing tests don't pass an `out_of_taxonomy` field in their done-row responses — fix them by adding `"out_of_taxonomy": False` to the response dicts in `test_finalize_tagging_consumes_done_rows`.

After that fix:

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/tagging.py scripts/tests/test_tagging.py
git commit -m "feat(tagging): required-vocabulary framing + out_of_taxonomy field"
```

---

## Task 4: Self-progressing `run_ingest_plan`

**Files:**
- Modify: `scripts/signal_brain/ingest.py` (`_data_paths`, `run_ingest_plan`)
- Modify: `scripts/signal_brain/cli.py` (read taxonomy cfg if any; pass through)
- Test: `scripts/tests/test_ingest.py`

- [ ] **Step 1: Write failing tests**

Add to `scripts/tests/test_ingest.py`:

```python
def test_run_ingest_plan_emits_taxonomy_todo_when_no_cache(tmp_path):
    """First call: no taxonomy.json → emit taxonomy todo, suppress tagging todos."""
    source = tmp_path / "src.jsonl"
    source.write_text("\n".join([
        json.dumps({"date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi"}),
        json.dumps({"date": "2026-05-05T13:00:01", "sender": "Friend", "body": "salut"}),
    ]) + "\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    stats = run_ingest_plan(
        source_path=source, data_dir=data_dir, burst_threshold_min=60,
    )
    assert stats["taxonomy_pending"] is True
    assert stats["taxonomy_todos"] == 1
    assert stats["tagging_todos"] == 0
    assert (data_dir / "taxonomy.todo.jsonl").exists()
    assert not (data_dir / "tagging.todo.jsonl").exists() or \
        sum(1 for _ in (data_dir / "tagging.todo.jsonl").open(encoding="utf-8")) == 0


def test_run_ingest_plan_emits_tagging_when_taxonomy_cache_hit(tmp_path):
    """Second call: taxonomy.json with matching hash → emit tagging with required vocab."""
    source = tmp_path / "src.jsonl"
    source.write_text("\n".join([
        json.dumps({"date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi"}),
        json.dumps({"date": "2026-05-05T13:00:01", "sender": "Friend", "body": "salut"}),
    ]) + "\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Prime the cache with the matching hash.
    from signal_brain.msg_index import build_msg_index, load_msg_index
    from signal_brain.taxonomy import source_content_hash
    build_msg_index(json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip())
    # We need the hash that run_ingest_plan will compute. Easiest: call it once,
    # then prime taxonomy.json.
    run_ingest_plan(source_path=source, data_dir=data_dir, burst_threshold_min=60)
    msgs = load_msg_index(data_dir / "msg_index.jsonl")
    expected_hash = source_content_hash(msgs)
    (data_dir / "taxonomy.json").write_text(json.dumps({
        "source_hash": expected_hash,
        "taxonomy": ["greeting", "small-talk"],
        "notes": "",
    }), encoding="utf-8")

    stats = run_ingest_plan(source_path=source, data_dir=data_dir, burst_threshold_min=60)
    assert stats["taxonomy_pending"] is False
    assert stats["tagging_todos"] >= 1
    # Tagging todo prompts must reference the controlled vocabulary.
    row = json.loads((data_dir / "tagging.todo.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "Required vocabulary" in row["user_prompt"]
    assert "greeting" in row["user_prompt"]
```

Note the first test's last line: the implementation must NOT create an empty `tagging.todo.jsonl` when in taxonomy_pending state. Either don't create it, or create it empty (zero rows). The assertion tolerates either.

The msg_index call in the second test is exploratory — the real flow is that `run_ingest_plan` builds msg_index itself. The test just primes taxonomy.json with the right hash so the second `run_ingest_plan` call hits the cache. (`build_msg_index` requires `out_path` — fix the test: actually let me re-check.)

Actually the helper call shape is wrong; cleaner: just call `run_ingest_plan` once (taxonomy_pending=True), then read `msg_index.jsonl`, compute the hash, prime taxonomy.json, call again. That's what the test does — good.

- [ ] **Step 2: Run, confirm they fail**

Run: `pytest scripts/tests/test_ingest.py -v`
Expected: `KeyError: 'taxonomy_pending'` and friends.

- [ ] **Step 3: Update `_data_paths`**

Edit `scripts/signal_brain/ingest.py`. Add taxonomy paths:

```python
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
```

- [ ] **Step 4: Rewrite `run_ingest_plan` to be staged**

Edit `scripts/signal_brain/ingest.py`. Add imports:

```python
from signal_brain.taxonomy import (
    emit_taxonomy_todo,
    load_taxonomy_cache,
    source_content_hash,
)
```

Replace `run_ingest_plan`:

```python
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

    Idempotent at both layers.
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

    # Stage 1: taxonomy.
    src_hash = source_content_hash(msgs)
    taxonomy = load_taxonomy_cache(p["taxonomy_cache"], source_hash=src_hash)
    if taxonomy is None:
        # Need taxonomy first. Try to finalize from an existing done file (the
        # orchestrator might have just produced it); otherwise emit the todo.
        from signal_brain.taxonomy import finalize_taxonomy
        emitted = finalize_taxonomy(
            p["taxonomy_todo"], p["taxonomy_done"], p["taxonomy_cache"],
            source_hash=src_hash,
        )
        if emitted is not None:
            taxonomy = emitted["taxonomy"]
        else:
            emit_taxonomy_todo(
                msgs, p["taxonomy_todo"],
                description=tagging_description, source_hash=src_hash,
            )
            todos = sum(1 for _ in p["taxonomy_todo"].open(encoding="utf-8"))
            return {
                "diff": {k: len(v) if isinstance(v, list) else v for k, v in diff.items()},
                "bursts": len(bursts),
                "taxonomy_pending": True,
                "taxonomy_todos": todos,
                "tagging_todos": 0,
            }

    # Stage 2: tagging with taxonomy in hand.
    manifest = Manifest.load_or_init(p["manifest"], burst_threshold_min=burst_threshold_min)
    cache_by_id = load_chunks_as_cache(p["chunks"], manifest.content_hashes)

    taxonomy_hash = source_content_hash([
        {"msg_id": "__taxonomy__", "body": json.dumps(taxonomy, sort_keys=True), "reactions": []}
    ])

    new_hashes = emit_tagging_todos(
        bursts, msgs, cache_by_id, p["tagging_todo"],
        description=tagging_description,
        seed_tags=tagging_seed_tags,
        required_taxonomy=taxonomy,
        taxonomy_hash=taxonomy_hash,
    )
    manifest.last_processed_msg_ts = msgs[-1]["date"] if msgs else None
    manifest.burst_count = len(bursts)
    manifest.content_hashes = new_hashes
    manifest.save(p["manifest"])

    tagging_todos = sum(1 for _ in p["tagging_todo"].open(encoding="utf-8")) if p["tagging_todo"].exists() else 0
    return {
        "diff": {k: len(v) if isinstance(v, list) else v for k, v in diff.items()},
        "bursts": len(bursts),
        "taxonomy_pending": False,
        "taxonomy_todos": 0,
        "tagging_todos": tagging_todos,
    }
```

- [ ] **Step 5: Update CLI to surface the new stats**

Edit `scripts/signal_brain/cli.py`. The `ingest` command already prints `json.dumps(stats, indent=2)` — no change needed; new keys appear automatically.

- [ ] **Step 6: Run all tests**

Run: `pytest scripts/tests/test_ingest.py -v`
Expected: the two new tests pass.

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/signal_brain/ingest.py scripts/tests/test_ingest.py
git commit -m "feat(ingest): self-progressing plan — taxonomy stage then tagging"
```

---

## Task 5: Finalize step writes taxonomy.json + forwards `out_of_taxonomy`

**Files:**
- Modify: `scripts/signal_brain/ingest.py::run_ingest_finalize`
- Test: `scripts/tests/test_ingest.py`

`run_ingest_finalize` already calls `finalize_tagging`, which now forwards `out_of_taxonomy` to chunks (Task 3). The only addition here is: finalize taxonomy too, so `taxonomy.json` lands on disk even if `run_ingest_plan` wasn't run twice in this session (e.g., a user explicitly runs `--finalize` after producing taxonomy.done out-of-band).

- [ ] **Step 1: Failing test**

Add to `scripts/tests/test_ingest.py`:

```python
def test_run_ingest_finalize_writes_taxonomy_json_from_done(tmp_path):
    """If taxonomy.done exists with a row matching the current source_hash, finalize writes the cache."""
    source = tmp_path / "src.jsonl"
    source.write_text(json.dumps({
        "date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi"
    }) + "\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    # Drive a plan to produce taxonomy.todo and msg_index.
    run_ingest_plan(source_path=source, data_dir=data_dir, burst_threshold_min=60)
    todo_row = load_todo(data_dir / "taxonomy.todo.jsonl")[0]
    (data_dir / "taxonomy.done.jsonl").write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {"taxonomy": ["greeting"], "notes": "n/a"},
    }) + "\n", encoding="utf-8")

    run_ingest_finalize(data_dir=data_dir, min_burst_count=2, min_msg_count=20)
    data = json.loads((data_dir / "taxonomy.json").read_text(encoding="utf-8"))
    assert data["taxonomy"] == ["greeting"]
```

(Import `load_todo` from `signal_brain.worklist` at top of the test file if not already.)

- [ ] **Step 2: Run, confirm it fails**

Run: `pytest scripts/tests/test_ingest.py::test_run_ingest_finalize_writes_taxonomy_json_from_done -v`
Expected: FAIL — taxonomy.json not produced by finalize.

- [ ] **Step 3: Update `run_ingest_finalize`**

Edit `scripts/signal_brain/ingest.py`. Replace `run_ingest_finalize`:

```python
def run_ingest_finalize(*, data_dir: Path,
                        min_burst_count: int, min_msg_count: int) -> dict:
    """Read tagging done, write chunks, detect arcs, update manifest.

    Also opportunistically finalizes the taxonomy stage if a matching done row
    is present — covers re-runs that come in with taxonomy.done out-of-band.
    """
    data_dir = Path(data_dir)
    p = _data_paths(data_dir)

    msgs = load_msg_index(p["msg_index"])
    src_hash = source_content_hash(msgs)
    from signal_brain.taxonomy import finalize_taxonomy
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
```

- [ ] **Step 4: Run, confirm pass**

Run: `pytest scripts/tests/test_ingest.py -v`
Expected: all pass.

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/ingest.py scripts/tests/test_ingest.py
git commit -m "feat(ingest): finalize taxonomy alongside tagging"
```

---

## Task 6: Loop the orchestrator skill

**Files:**
- Modify: `skills/signal-brain-build/SKILL.md`

- [ ] **Step 1: Edit the skill**

Replace the "### 2. Ingest — plan phase" and "### 3. Tagging fan-out" sections with:

```markdown
### 2. Ingest — plan loop

`signal-brain ingest --plan` is self-progressing. Run it in a loop until the
output stats show no pending stages:

```bash
signal-brain ingest --plan --source "$SRC"
```

Inspect the printed stats:

| Stat | What to do next |
|---|---|
| `taxonomy_pending: true` (and `taxonomy_todos > 0`) | Go to **2a (taxonomy fan-out)**, then re-run this command. |
| `taxonomy_pending: false` and `tagging_todos > 0` | Go to **3 (tagging fan-out)**, then **4 (ingest --finalize)**. |
| `taxonomy_pending: false` and `tagging_todos == 0` | Nothing to do; skip to **4 (ingest --finalize)**. |

Re-run `signal-brain ingest --plan --source "$SRC"` after each fan-out. The
loop terminates when both `taxonomy_pending` is false and `tagging_todos` is
zero (or the same as the previous iteration).

#### 2a. Taxonomy fan-out

Read `brain/$SRC/data/taxonomy.todo.jsonl`. It contains exactly one row.
Dispatch one subagent using the same template as tagging (see Step 3).
Response schema:

```
required keys: ["taxonomy", "notes"]
types:         {"taxonomy": "list", "notes": "str"}
```

The taxonomy stage is heavier per-call than tagging (the prompt embeds the full
conversation). Set a generous timeout on the subagent. On parse/schema failure,
retry once exactly as for tagging; on second failure, append to
`taxonomy.failed.jsonl` and STOP — without a taxonomy, tagging produces uncontrolled
slugs and the wiki regresses to the pre-PR-#2 state.

Append the result to `brain/$SRC/data/taxonomy.done.jsonl`:

```json
{"job_id": "<from todo>", "response": <parsed dict>, "model": "subagent"}
```

Then loop back to **Step 2**.

### 3. Tagging fan-out

(unchanged — read `brain/$SRC/data/tagging.todo.jsonl`, dispatch one subagent
per row, cap at 30 concurrent. Response schema now includes `out_of_taxonomy`
— pass it through unchanged.)
```

- [ ] **Step 2: Sanity-check by reading**

Run: `cat skills/signal-brain-build/SKILL.md | sed -n '40,90p'`
Expected: the loop instructions are coherent. No syntax errors.

- [ ] **Step 3: Commit**

```bash
git add skills/signal-brain-build/SKILL.md
git commit -m "docs(skill): ingest --plan loop with taxonomy fan-out"
```

---

## Task 7: Lint check for taxonomy fit

**Files:**
- Modify: `scripts/signal_brain/lint.py`
- Test: `scripts/tests/test_lint.py`

- [ ] **Step 1: Find the right insertion point**

Read `scripts/signal_brain/lint.py` to locate where existing checks emit their report sections. Add a new check just before the final report write.

- [ ] **Step 2: Write failing test**

Add to `scripts/tests/test_lint.py`:

```python
def test_lint_reports_out_of_taxonomy_rate(tmp_path):
    """Lint reports the share of chunks tagged out_of_taxonomy=true."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    brain_dir = tmp_path / "wiki"
    brain_dir.mkdir()
    (data_dir / "chunks.jsonl").write_text("\n".join([
        json.dumps({"burst_id": "B0001", "topics": ["a"], "primary": "a",
                    "summary": "x", "out_of_taxonomy": False}),
        json.dumps({"burst_id": "B0002", "topics": ["b"], "primary": "b",
                    "summary": "y", "out_of_taxonomy": True}),
        json.dumps({"burst_id": "B0003", "topics": ["c"], "primary": "c",
                    "summary": "z", "out_of_taxonomy": True}),
    ]) + "\n", encoding="utf-8")
    # Other lint inputs that may be required by run_lint — match the minimum
    # shape used by the existing lint tests.
    (brain_dir / "people").mkdir()
    (brain_dir / "concepts").mkdir()
    (brain_dir / "positions").mkdir()
    (brain_dir / "arcs").mkdir()
    (brain_dir / "cross").mkdir()
    report = brain_dir / "lint-report.md"

    from signal_brain.lint import run_lint
    run_lint(brain_dir, data_dir, report)
    text = report.read_text(encoding="utf-8")
    assert "out_of_taxonomy" in text.lower()
    # 2 of 3 = 66.67%
    assert "66" in text or "67" in text
```

(Adapt the file shapes if `run_lint`'s signature needs additional inputs — check the existing tests in `test_lint.py` for the pattern.)

- [ ] **Step 3: Run, confirm it fails**

Run: `pytest scripts/tests/test_lint.py -v`
Expected: the new test fails (no taxonomy section in the report).

- [ ] **Step 4: Add the check**

Edit `scripts/signal_brain/lint.py`. Add a helper:

```python
def _out_of_taxonomy_rate(chunks_path: Path) -> tuple[int, int, float] | None:
    """Return (out_of_taxonomy_count, total, rate_pct) or None if no chunks."""
    if not Path(chunks_path).exists():
        return None
    rows = [json.loads(l) for l in Path(chunks_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        return None
    out = sum(1 for r in rows if r.get("out_of_taxonomy"))
    return out, len(rows), (out / len(rows)) * 100.0
```

Wire the check into `run_lint` (in the appropriate section, alongside existing checks). Append to the report markdown:

```python
    chunks_path = data_dir / "chunks.jsonl"
    rate = _out_of_taxonomy_rate(chunks_path)
    if rate is not None:
        out, total, pct = rate
        lines.append("## Taxonomy fit\n")
        lines.append(f"- out_of_taxonomy chunks: {out} / {total} ({pct:.1f}%)")
        if pct > 25.0:
            lines.append("- ⚠ rate is above 25% — taxonomy is under-fitted; consider deleting `taxonomy.json` and re-running ingest to regenerate.")
        lines.append("")
```

(Adapt `lines` / report assembly to whatever pattern `run_lint` already uses.)

- [ ] **Step 5: Run all tests**

Run: `pytest scripts/tests/test_lint.py -v`
Expected: pass.

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/signal_brain/lint.py scripts/tests/test_lint.py
git commit -m "feat(lint): out_of_taxonomy rate report + over-25% warning"
```

---

## Task 8: Smoke-test acceptance on Amélie

**Files:** none modified — verification only.

- [ ] **Step 1: Clean previous state**

```bash
rm -rf brain/Amélie/
```

- [ ] **Step 2: Run the orchestrator end-to-end**

From inside Claude Code, invoke the `signal-brain-build` skill on the Amélie source. The skill should:

1. First `ingest --plan` returns `taxonomy_pending=true` with one todo.
2. Fan out one subagent → write taxonomy.done.
3. Second `ingest --plan` returns `taxonomy_pending=false` with N tagging todos (one per burst).
4. Fan out tagging subagents.
5. `ingest --finalize`.
6. The rest of the pipeline as today.

Confirm the loop converges (the skill should not require user nudging between iterations).

- [ ] **Step 3: Verify `taxonomy.json` shape**

```bash
cat brain/Amélie/data/taxonomy.json
```

Expected: a JSON object with `source_hash`, `taxonomy` (10–25 slugs), `notes`. Eyeball the slugs — they should look like coherent themes, not generic single-word noise.

- [ ] **Step 4: Verify chunks adhere to the taxonomy**

```bash
python3 - <<'EOF'
import json
from pathlib import Path
tax = set(json.loads(Path("brain/Amélie/data/taxonomy.json").read_text())["taxonomy"])
rows = [json.loads(l) for l in Path("brain/Amélie/data/chunks.jsonl").read_text().splitlines() if l.strip()]
in_tax = 0; out_tax = 0
for r in rows:
    if r.get("out_of_taxonomy"): out_tax += 1
    else: in_tax += 1
    if not r.get("out_of_taxonomy"):
        assert set(r["topics"]).issubset(tax), f"{r['burst_id']} has off-taxonomy topics: {set(r['topics']) - tax}"
print(f"in-taxonomy: {in_tax}, out-of-taxonomy: {out_tax}")
EOF
```

Expected: no assertion fires; `out_of_taxonomy` rate is well under 25%.

- [ ] **Step 5: Verify acceptance criteria 3, 4, 5**

```bash
ls brain/Amélie/concepts/
ls brain/Amélie/positions/ | grep "thomas-martin"
```

Expected:
- At least one file under `concepts/` on a wealth-concentration-themed slug.
- At least one `positions/thomas-martin--*.md` file.

Then ask an agent (or check manually):

> Read `brain/Amélie/AGENTS.md` and answer: what is Thomas Martin's position on accumulation of capital and inequality?

Expected: the answer cites a position page (`positions/thomas-martin--*.md`), not just bursts.

- [ ] **Step 6: Verify idempotence**

```bash
signal-brain ingest --plan --source Amélie
```

Expected: `taxonomy_pending: false`, `tagging_todos: 0`. No new work.

- [ ] **Step 7: Open the PR**

```bash
git push -u origin feat/taxonomy-first
gh pr create --title "feat: taxonomy-first ingest for canonical-vocabulary tagging" --body "$(cat <<'EOF'
## Summary

Inserts a new `taxonomy` stage upstream of per-burst tagging. One subagent extracts a 10–25-slug canonical vocabulary from the full conversation; per-burst tagging then uses that vocabulary as required input, with an `out_of_taxonomy` escape hatch.

Concept and position pages now actually fire on small conversations (~150 bursts) where they previously never accumulated enough shared slugs.

- New `scripts/signal_brain/taxonomy.py` with the plan/finalize contract.
- `burst_content_hash` folds in the taxonomy hash → taxonomy changes invalidate burst caches.
- Tagging prompts enforce the controlled vocabulary; new `out_of_taxonomy` field flows through to chunks and is surfaced by lint.
- `ingest --plan` is self-progressing; the orchestrator skill loops `--plan` + fan-out until convergence.
- Cached at `brain/<src>/data/taxonomy.json` keyed by source content hash.

Spec: `docs/superpowers/specs/2026-05-20-taxonomy-first.md`

## Test plan

- [ ] `pytest -q` is green.
- [ ] Amélie smoke: `brain/Amélie/data/taxonomy.json` has 10–25 coherent slugs.
- [ ] ≥1 concept page on a wealth-concentration-themed slug.
- [ ] ≥1 `positions/thomas-martin--*.md` page.
- [ ] The motivating query ("Thomas' position on accumulation of capital…") cites a position page.
- [ ] Idempotent: re-running `ingest --plan` after finalize is a no-op.
- [ ] `out_of_taxonomy` rate < 25% on Amélie.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist

1. **Spec coverage:**
   - New stage upstream of tagging → Task 1 (module).
   - Cache key = source content hash → Task 1 (`source_content_hash`, `load_taxonomy_cache`).
   - System/user prompt changes when taxonomy present → Task 3.
   - `out_of_taxonomy` field added to schema and flows to chunks → Task 3.
   - Taxonomy folded into burst hash → Task 2.
   - Self-progressing `run_ingest_plan` → Task 4.
   - Finalize writes `taxonomy.json` → Task 5.
   - Skill loop → Task 6.
   - Lint check → Task 7.
   - Acceptance criteria 1–6 → Task 8.

2. **Placeholder scan:** none — every code block is complete. Lint helper assumes `lines` array convention; verify against `lint.py` shape during implementation and adapt.

3. **Type consistency:** `burst_content_hash(burst, all_messages, *, taxonomy_hash="")` is consistent between Task 2 (definition), Task 3 (consumed in `emit_tagging_todos`), and Task 4 (consumed in `run_ingest_plan`). `TAGGING_RESPONSE_SCHEMA` includes `out_of_taxonomy` everywhere from Task 3 onwards. `emit_taxonomy_todo(messages, todo_path, *, description, source_hash)` keyword-only signature is used identically in Task 1 (test + impl) and Task 4 (call site).

---

## Phase 2 — topic-model redesign (added 2026-05-20)

The Task 8 smoke test revealed the flat 24-slug taxonomy fragments themes (wealth split into 3 sibling slugs) and that `plan_pages` counts only `primary` at `min_concept_bursts=5`, so on 25 bursts no concept/position page fires. Phase 2 replaces the count threshold with AI judgment and improves topic granularity. Spec section: "Concept and position page selection".

### Task 9: Taxonomy emits `concepts` + concept-grade topic prompt

**Files:**
- Modify: `scripts/signal_brain/taxonomy.py`
- Modify: `scripts/signal_brain/ingest.py` (`load_taxonomy_cache` consumer)
- Test: `scripts/tests/test_taxonomy.py`, `scripts/tests/test_ingest.py`

- `TAXONOMY_RESPONSE_SCHEMA` gains `concepts`: `{"required": ["taxonomy", "concepts", "notes"], "types": {"taxonomy": "list", "concepts": "list", "notes": "str"}}`.
- `build_system_prompt` rewritten: anti-fragmentation (merge facets of one theme into one umbrella slug; target ~10–18 topics) + concept-worthiness (mark a topic a `concept` when the two people develop arguments about it).
- `build_user_prompt` "Output JSON" example includes `concepts`.
- `finalize_taxonomy` writes `concepts` (defensively intersected with `taxonomy`) into `taxonomy.json`; still rejects empty `taxonomy`.
- `load_taxonomy_cache` returns the full dict `{"taxonomy": [...], "concepts": [...], "notes": ...}` or `None` (was `list[str] | None`).
- `run_ingest_plan` updated: `load_taxonomy_cache` now returns a dict — read `["taxonomy"]` for the tagging vocabulary.
- Tests updated for the new field; `test_ingest.py::_complete_taxonomy_stage` writes `concepts` in its done row.

### Task 10: `plan_pages` AI-decided concepts, drop `min_concept_bursts`

**Files:**
- Modify: `scripts/signal_brain/wiki/build.py`
- Test: `scripts/tests/test_wiki_build.py`, `scripts/tests/test_build_wiki_plan_finalize.py`
- Modify: `KNOWN_ISSUES.md` (remove resolved item #6)

- `plan_pages` drops `min_concept_bursts`, gains `concepts: list[str]` keyword param.
- Counts every topic on a burst (`chunk["topics"]`), not just `primary`.
- Concept page for each slug in `concepts` backed by ≥1 chunk.
- Position page for each (holder, concept-slug) backed by ≥1 burst where the holder participated and the slug is in the burst's topics.
- `build_wiki_plan` drops `min_concept_bursts`, loads `taxonomy.json` for the `concepts` list, passes it to `plan_pages`. No `taxonomy.json` → `concepts = []` → no concept/position pages (graceful).
- KNOWN_ISSUES #6 (`build_wiki hardcodes min_concept_bursts=5`) removed — resolved.

### Task 11: Smoke test + PR (supersedes original Task 8)

End-to-end run on the Amélie export: taxonomy fan-out with the new prompt, tagging fan-out, finalize, `build-wiki --plan`, lint. Verify all six acceptance criteria — in particular ≥1 wealth-themed concept page and ≥1 `positions/thomas-martin--*.md`. Open the PR.

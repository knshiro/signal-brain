"""Plan/finalize worklist: file-based RPC between Python and the agent.

Each stage that used to call the LLM (tagging, wiki synthesis, lateral linking,
burst evaluation) now emits a `*.todo.jsonl` file in --plan phase and reads a
`*.done.jsonl` file in --finalize phase. The agent fills in done.jsonl by
dispatching one subagent per todo row.

Row schemas
-----------

Todo row::

    {
      "job_id":          "16 hex chars, stable hash of (stage, kind, system, user)",
      "stage":           "tagging" | "synthesis" | "lateral-link" | "evaluate-bursts",
      "kind":            "burst" | "page-person" | "page-concept" | ...,
      "system_prompt":   "...",
      "user_prompt":     "...",
      "response_schema": { "required": [...], "types": {...} },
      "context":         { ... stage-specific metadata used at finalize ... }
    }

Done row::

    {
      "job_id":  "...",
      "response": { ... matches response_schema ... },
      "model":   "subagent" or whatever the dispatcher recorded (informational),
      "elapsed_s": 12.3
    }

Idempotence
-----------
`stable_job_id` hashes (stage, kind, system, user) so the same logical task
always gets the same id. `emit` is a no-op when a row with the same job_id is
already present, so re-running --plan is safe.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class WorklistError(Exception):
    """Raised when a response fails schema validation or parsing."""


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def stable_job_id(stage: str, kind: str, system: str, user: str) -> str:
    """sha256(stage|kind|system|user) -> first 16 hex chars."""
    h = hashlib.sha256()
    h.update(stage.encode("utf-8"))
    h.update(b"\x1f")
    h.update(kind.encode("utf-8"))
    h.update(b"\x1f")
    h.update(system.encode("utf-8"))
    h.update(b"\x1f")
    h.update(user.encode("utf-8"))
    return h.hexdigest()[:16]


def emit(
    todo_path: Path,
    *,
    stage: str,
    kind: str,
    system: str,
    user: str,
    response_schema: dict,
    context: dict,
) -> str:
    """Append a todo row. Returns job_id. No-op if the row already exists.

    The file is created if missing. Existing rows are read once to dedupe by
    job_id; new row is appended at the end. UTF-8 explicit.
    """
    todo_path = Path(todo_path)
    job_id = stable_job_id(stage, kind, system, user)
    existing_ids = {row["job_id"] for row in load_todo(todo_path)}
    if job_id in existing_ids:
        return job_id
    todo_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "job_id": job_id,
        "stage": stage,
        "kind": kind,
        "system_prompt": system,
        "user_prompt": user,
        "response_schema": response_schema,
        "context": context,
    }
    with todo_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return job_id


def load_todo(todo_path: Path) -> list[dict]:
    """Read all todo rows in insertion order. Empty list if file missing."""
    todo_path = Path(todo_path)
    if not todo_path.exists():
        return []
    rows: list[dict] = []
    for line in todo_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def load_done(done_path: Path) -> dict[str, dict]:
    """Read done rows. Returns {job_id: row}. Empty dict if file missing.

    On duplicate job_ids in the file, the last one wins (so the agent can
    overwrite a failed retry by appending a fresh row).
    """
    done_path = Path(done_path)
    if not done_path.exists():
        return {}
    out: dict[str, dict] = {}
    for line in done_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[row["job_id"]] = row
    return out


_PY_TYPE = {
    "str": str,
    "int": int,
    "float": (int, float),
    "bool": bool,
    "list": list,
    "dict": dict,
}


def validate_response(response: dict, schema: dict) -> None:
    """Lightweight schema check. Not full JSON Schema — just required keys + types.

    Schema shape::

        {"required": ["k1", "k2"], "types": {"k1": "str", "k2": "list"}}

    Raises WorklistError on violation. Extra keys are ignored.
    """
    if not isinstance(response, dict):
        raise WorklistError(f"Response must be a JSON object, got {type(response).__name__}")
    for key in schema.get("required", []):
        if key not in response:
            raise WorklistError(f"Missing required key: {key!r}")
    for key, type_name in schema.get("types", {}).items():
        if key not in response:
            continue
        expected = _PY_TYPE.get(type_name)
        if expected is None:
            raise WorklistError(f"Unknown schema type {type_name!r} for key {key!r}")
        if not isinstance(response[key], expected):
            raise WorklistError(
                f"Key {key!r}: expected {type_name}, got {type(response[key]).__name__}"
            )


def parse_subagent_response(text: str) -> dict:
    """Strip optional ```json``` fence, json.loads.

    Mirrors the fence-stripping behavior of the retired LLMClient.complete_json so
    subagents that wrap their output (despite the prompt asking otherwise) still
    parse cleanly.
    """
    stripped = text.strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise WorklistError(f"Response is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise WorklistError(f"Response must be a JSON object, got {type(parsed).__name__}")
    return parsed

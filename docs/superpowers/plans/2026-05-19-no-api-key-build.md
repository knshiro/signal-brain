# Implementation plan — Run signal-brain without `ANTHROPIC_API_KEY`

> **For agentic workers:** Use `superpowers:subagent-driven-development` to execute this plan. Tasks A, B, C, D are mostly independent once Task A's `worklist.py` exists, so they can be dispatched in parallel.

**Spec:** `docs/superpowers/specs/2026-05-19-no-api-key-build-redesign.md`
**Branch:** `feat/no-api-key-build`

## Sequencing

```
        ┌──────────────┐
        │  Task A      │  worklist.py + ingest plan/finalize
        │  (foundation)│
        └──────┬───────┘
               │
   ┌───────────┼──────────────┬──────────────┐
   ▼           ▼              ▼              ▼
┌─────┐    ┌──────┐       ┌──────┐       ┌──────┐
│ B   │    │ C    │       │ D    │       │ E    │
│wiki │    │link+ │       │skill │       │drop  │
│     │    │eval  │       │      │       │llm.py│
└──┬──┘    └──┬───┘       └──┬───┘       └──┬───┘
   └──────────┴──────────────┴──────────────┘
                       │
                       ▼
                 ┌──────────┐
                 │ Task F   │  full test pass + smoke
                 │ Task G   │  commit + PR
                 └──────────┘
```

Tasks B, C, D can be dispatched as parallel subagents after A merges into the working branch. Task E depends on B, C complete (so all four call sites are migrated).

---

## Task A — worklist module + ingest refactor

**Goal:** Land the foundation: a `worklist.py` module and a `tagging.py`/`ingest.py`/CLI refactor that emits a tagging todo file and finalizes from a tagging done file. After this task, `signal-brain ingest --plan` works without any API key.

### A1. `scripts/signal_brain/worklist.py`

Public surface:

```python
def stable_job_id(stage: str, kind: str, system: str, user: str) -> str:
    """sha256(stage|kind|system|user) -> first 16 hex chars. Stable across runs."""

def emit(todo_path: Path, *, stage: str, kind: str,
         system: str, user: str,
         response_schema: dict, context: dict) -> str:
    """Append a todo row (idempotent by job_id). Returns job_id.

    Skips append if a row with the same job_id is already present.
    UTF-8 explicit. Atomic-ish: append-only writes.
    """

def load_done(done_path: Path) -> dict[str, dict]:
    """job_id -> done-row dict. Returns {} if file missing."""

def load_todo(todo_path: Path) -> list[dict]:
    """Read all todo rows in order. Returns [] if file missing."""

class WorklistError(Exception): ...

def validate_response(response: dict, schema: dict) -> None:
    """Lightweight schema check: required keys present, type matches.
    Raises WorklistError on violation. Not a full JSON Schema implementation —
    just enough to catch common subagent malformations.
    """

def parse_subagent_response(text: str) -> dict:
    """Strip optional ```json``` fences, json.loads. Mirrors today's
    LLMClient.complete_json fence-stripping behavior.
    """
```

Schema check (`validate_response`):
- Schema is a dict like `{"required": ["topics", "primary", "summary"], "types": {"topics": "list", "primary": "str", "summary": "str"}}`.
- Missing required key → raise.
- Wrong type → raise.
- Extra keys ignored.

UTF-8 explicit on every file I/O (CLAUDE.md convention).

### A2. Refactor `tagging.py`

Split `tag_bursts` into two functions:

```python
def emit_tagging_todos(
    bursts: list[dict], all_messages: list[dict],
    cache_by_id: dict[str, dict],
    todo_path: Path,
    *, description: str = "",
    seed_tags: list[str] | None = None,
) -> dict[str, str]:
    """For each burst whose content hash differs from cache, emit a todo row.
    Returns id->hash map (the manifest will save this)."""

def finalize_tagging(
    bursts: list[dict],
    cache_by_id: dict[str, dict],
    todo_path: Path,
    done_path: Path,
    chunks_path: Path,
) -> dict:
    """Read done.jsonl, merge with cache for unchanged bursts, write chunks.jsonl.
    Raises if a todo row has no matching done row (with job_id list).
    Returns {"new": N, "cached": M, "missing": [...]}.
    """
```

Today's `tag_bursts(...)` becomes a thin wrapper that calls both in sequence with an in-process LLM if `llm` is provided (kept only for tests until we drop it). The CLI path no longer uses the wrapper.

### A3. Refactor `ingest.py` and `cli.py`

Add `--plan` / `--finalize` flags to `ingest`:

```python
@main.command()
@source_option
@click.option("--plan", "phase", flag_value="plan", default=None)
@click.option("--finalize", "phase", flag_value="finalize", default=None)
def ingest(source, phase):
    """Build/refresh the data layer. Two-phase: --plan emits todo, --finalize reads done."""
    if phase is None:
        raise click.ClickException(
            "Use --plan or --finalize. Legacy single-phase ingest required ANTHROPIC_API_KEY.\n"
            "See docs/superpowers/specs/2026-05-19-no-api-key-build-redesign.md"
        )
    # ... dispatch to run_ingest_plan or run_ingest_finalize
```

`run_ingest_data_layer` (in `ingest.py`) is split:

- `run_ingest_plan(source_path, data_dir, burst_threshold_min, tagging_description, tagging_seed_tags)` → build msg_index, bursts, emit tagging todos. Return stats. **No LLM.**
- `run_ingest_finalize(data_dir, min_burst_count, min_msg_count)` → read tagging done, write chunks, detect arcs, write arcs + manifest. Return stats. **No LLM.**

### A4. Tests

- `scripts/tests/test_worklist.py`: emit dedupes by job_id; load_done returns map; missing file → empty map; validate_response happy/sad; parse_subagent_response strips fences.
- `scripts/tests/test_ingest_plan_finalize.py`: round-trip on the mini fixture. Plan emits N todos, hand-write done rows (bypassing the LLM), finalize produces a `chunks.jsonl` byte-identical to the LLM-mocked baseline.

### A5. Acceptance

- `pytest -q scripts/tests/test_worklist.py scripts/tests/test_ingest_plan_finalize.py` passes.
- `signal-brain ingest --plan --source <s>` runs without `ANTHROPIC_API_KEY`.
- `signal-brain ingest --finalize --source <s>` runs without `ANTHROPIC_API_KEY` if done.jsonl exists.

---

## Task B — wiki page generators (5 types)

**Goal:** Convert each generator from "call LLM, validate, return rendered page" to "build prompts, return (system, user, schema, context_for_finalize)". `build_wiki` becomes plan/finalize.

### B1. New shared helper

Add to `scripts/signal_brain/wiki/build.py` or a new `wiki/prompts.py`:

```python
PAGE_RESPONSE_SCHEMA = {
    "required": ["body"],
    "types": {"body": "str"},
}
```

### B2. Refactor each generator

For each of `people.py`, `concepts.py`, `positions.py`, `arcs.py`, `cross.py`:

- Replace the function `generate_*_page(*, ..., llm) -> str` with two functions:

  ```python
  def build_*_prompts(*, ...) -> tuple[str, str, dict, dict]:
      """Return (system, user, response_schema, planned_frontmatter)."""

  def render_*_page(planned_fm: dict, body: str) -> str:
      """Validate + render. Raises SchemaError on body schema mismatch."""
  ```

- Keep the existing `*_SYSTEM` and `*_USER` constants in place (and the subagent will receive them verbatim — they already say "Output body only").
- The frontmatter computation moves into `build_*_prompts` so finalize can attach it without re-running the prompt logic.

### B3. Refactor `wiki/build.py`

- `build_wiki_plan(*, data_dir, wiki_dir, me, todo_path, min_concept_bursts=5) -> dict`
  - Calls `plan_pages(...)`.
  - For each planned page, calls the appropriate `build_*_prompts`, then `worklist.emit(...)` with `context={"page_type": "...", "out_path": "...", "frontmatter": planned_fm}`.
  - Returns `{"pages_planned": N}`.
- `build_wiki_finalize(*, wiki_dir, todo_path, done_path) -> dict`
  - Reads done.jsonl.
  - For each done row: extract `body` from response, look up `out_path` and `frontmatter` from the matching todo row's context, call `render_*_page(fm, body)`, write to disk.
  - On schema violation: write a `synthesis.failed.jsonl` row, do **not** write the page, continue.
  - Returns `{"pages_written": N, "failed": M, "missing": [...]}`.

### B4. CLI

`signal-brain build-wiki --plan|--finalize --source <s>`. No-flag error like ingest.

### B5. Tests

- `scripts/tests/test_build_wiki_plan_finalize.py`: round-trip one page type per fixture. Plan emits 1 todo of each kind; hand-write done rows with valid bodies; finalize writes the .md files; bodies match a stored expected fixture (sanitized for date).
- One sad-path test: a done row with a body missing a required section → goes to `failed.jsonl`, no page written.

### B6. Acceptance

- All existing wiki tests pass (with their LLM mocks updated to the new function shapes).
- `signal-brain build-wiki --plan` works without key.
- Per-page schema validation still gates output.

---

## Task C — linking Stage 2 + evaluators

**Goal:** Same pattern, smaller surface.

### C1. `linking.py` Stage 2

```python
def run_stage2_plan(wiki_dir: Path, todo_path: Path, data_dir: Path) -> dict:
    """Scan pages, emit one lateral-link todo per page."""

def run_stage2_finalize(wiki_dir: Path, todo_path: Path, done_path: Path, data_dir: Path) -> dict:
    """Read done.jsonl, merge with Stage 1 graph, write link_graph.jsonl and update Related blocks."""
```

CLI: `signal-brain link --stage 2 --plan|--finalize`. `link --stage 1` stays deterministic and unchanged.

Response schema: `{"required": ["links"], "types": {"links": "list"}}`. Validation in finalize: drop any link that's not a string starting with `[[` and ending with `]]`; drop self-links; cap at 6.

### C2. `evaluators.py`

```python
def evaluate_bursts_plan(data_dir: Path, todo_path: Path, sample_size: int = 20) -> dict:
def evaluate_bursts_finalize(todo_path: Path, done_path: Path) -> dict:
```

CLI: `signal-brain evaluate-bursts --plan|--finalize`.

### C3. Tests

- `test_linking_plan_finalize.py`: hand-written done.jsonl with mixed valid/invalid links; finalize keeps only valid ones, merges with Stage 1, writes link_graph.
- `test_evaluators_plan_finalize.py`: feed done rows with each verdict; finalize aggregates counts correctly.

### C4. Acceptance

- All existing linking/eval tests pass.
- `signal-brain link --stage 2 --plan` and `signal-brain evaluate-bursts --plan` work without key.

---

## Task D — orchestrator skill + install script

**Goal:** Ship `skills/signal-brain-build/SKILL.md` and `scripts/install-skills.sh`. Update README + CLAUDE.md.

### D1. `skills/signal-brain-build/SKILL.md`

Frontmatter:

```yaml
---
name: signal-brain-build
description: >
  Build a Signal conversation brain end-to-end (ingest → wiki → links → lint)
  without an Anthropic API key. Use when the user says "build the brain",
  "run signal-brain", "regenerate the SébastienBéal brain", or invokes this
  skill directly. Drives the local Python pipeline through plan/finalize
  phases and dispatches subagents to do the LLM-shaped work.
user-invocable: true
---
```

Body (numbered steps, runtime-agnostic — uses "dispatch a subagent" language):

1. Resolve source. If `--source` not provided and exactly one directory exists under `out/`, use it. If multiple and the user didn't specify, surface the list and stop.
2. Run `signal-brain ingest --plan --source <s>`. Read `brain/<s>/data/tagging.todo.jsonl`.
3. **Tagging fan-out.** For each todo row, dispatch one subagent with the system+user prompts and the strict-JSON instruction. Cap concurrent dispatches at 30; batch sequentially if more. Collect responses, parse, validate against schema, write to `brain/<s>/data/tagging.done.jsonl`. On schema failure: one retry; second failure → log to `tagging.failed.jsonl`, continue.
4. Run `signal-brain ingest --finalize --source <s>`.
5. Run `signal-brain build-wiki --plan --source <s>`. Read `brain/<s>/data/synthesis.todo.jsonl`. Same fan-out pattern. Wiki page bodies are markdown wrapped in `{"body": "..."}`.
6. Run `signal-brain build-wiki --finalize --source <s>`.
7. Run `signal-brain build-index --source <s>`.
8. Run `signal-brain link --stage 1 --source <s>` (deterministic, no fan-out).
9. Run `signal-brain link --stage 2 --plan --source <s>`. Fan-out the link todos. Finalize.
10. Run `signal-brain lint --source <s>`.
11. Print a one-screen summary: pages written, bursts, arcs, lint findings, any failed jobs.

Include a "Subagent prompt template" section with the exact text to wrap around each todo row's system+user (the "Return ONE JSON object matching this schema, no markdown fences, no prose" boilerplate).

Include "If you are running on Codex" note: requires `[features] multi_agent = true` in `~/.codex/config.toml`. (Per `using-superpowers/references/codex-tools.md`.)

### D2. `scripts/install-skills.sh`

Per spec §9. Bash, `set -euo pipefail`, `ln -s` (symbolic, absolute target), idempotent. Skips clobbering non-symlinks.

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SKILLS_SRC="$REPO_ROOT/skills"
for runtime_dir in "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  mkdir -p "$runtime_dir"
  for skill_path in "$SKILLS_SRC"/*/; do
    name="$(basename "$skill_path")"
    target="$runtime_dir/$name"
    source_abs="${skill_path%/}"
    if [ -L "$target" ]; then rm "$target"
    elif [ -e "$target" ]; then echo "Skipping $target (exists, not a symlink)" >&2; continue
    fi
    ln -s "$source_abs" "$target"
    echo "Linked $target -> $source_abs"
  done
done
```

`chmod +x` it.

### D3. README + CLAUDE.md

- Remove `export ANTHROPIC_API_KEY=...` from setup instructions.
- Add `bash scripts/install-skills.sh` step.
- New "How to build the brain" section: "From inside Claude Code or Codex, invoke the `signal-brain-build` skill."
- Note Codex prerequisite: `multi_agent = true`.

### D4. Acceptance

- `bash scripts/install-skills.sh` creates two symbolic links and reports them.
- `ls -la ~/.claude/skills/signal-brain-build ~/.codex/skills/signal-brain-build` shows both as symlinks pointing into the repo.
- Re-running the script is idempotent.
- `cat ~/.claude/skills/signal-brain-build/SKILL.md` and `cat ~/.codex/skills/signal-brain-build/SKILL.md` both succeed.

---

## Task E — drop `llm.py` + `anthropic` runtime dep

After B, C are done and `llm.py` is no longer imported anywhere:

- `git rm scripts/signal_brain/llm.py`.
- Update tests that imported `LLMClient` → use direct done-file fixtures instead.
- `pyproject.toml`: move `anthropic` from runtime deps to `[project.optional-dependencies] dev` (or remove entirely if no tests need it).
- `CLAUDE.md`: drop `ANTHROPIC_API_KEY` from setup section.
- Grep the repo for `ANTHROPIC_API_KEY` and `anthropic` imports. Should be zero hits outside docs/historical plans.

---

## Task F — Full test pass + smoke

- `pytest -q` — all tests green.
- Manual smoke: with `ANTHROPIC_API_KEY` unset, run `signal-brain ingest --plan --source SébastienBéal`. Inspect `brain/SébastienBéal/data/tagging.todo.jsonl` — should have ~25 rows (one per burst). Hand-write a few fake done rows. Run `signal-brain ingest --finalize` — should produce a partial `chunks.jsonl`. Restore and let the orchestrator skill take over only if the user wants to test the full path.
- Document any items deferred to `KNOWN_ISSUES.md` (e.g., if Codex side can't be tested from here without switching runtime).

---

## Task G — Commit + PR

Commit per task (focused, conventional commits):

```
docs: spec — run signal-brain without ANTHROPIC_API_KEY
docs: implementation plan for no-API-key build
feat(worklist): job-based plan/finalize contract for LLM stages
refactor(tagging,ingest): emit/finalize via worklist
refactor(wiki): plan/finalize for all five page generators
refactor(linking,evaluators): plan/finalize Stage 2 and burst evaluator
feat(skill): orchestrator skill + symlink installer for Claude + Codex
chore: drop llm.py and anthropic runtime dep
docs: update README and CLAUDE.md (no API key needed)
```

Push, open PR:

```
gh pr create --title "feat: run signal-brain without ANTHROPIC_API_KEY (skill + subagents)" \
  --body "$(cat <<'EOF'
## Summary
- Replace direct Anthropic SDK calls with a plan/finalize worklist contract; LLM work is done by the agent's subagents.
- Ships an orchestrator skill `signal-brain-build` symlinked into both `~/.claude/skills/` and `~/.codex/skills/`.
- Drops `anthropic` from runtime deps; no API key needed to build a brain.

## Test plan
- [ ] `pytest -q` (offline, no API key)
- [ ] `bash scripts/install-skills.sh` — verify two symlinks
- [ ] From Claude Code: invoke `signal-brain-build` on the mini fixture
- [ ] (Optional) From Codex with `multi_agent = true`: invoke `signal-brain-build`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Out of scope for this PR

- KNOWN_ISSUES.md items #1, #3, #4 (orthogonal cleanups).
- A separate Codex-specific tool-mapping reference in the repo (codex-tools.md exists upstream in `superpowers/`; we don't need to duplicate it).
- Real-time progress streaming from subagents.

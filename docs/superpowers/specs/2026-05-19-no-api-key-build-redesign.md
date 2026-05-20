# Spec — Run signal-brain without ANTHROPIC_API_KEY (Claude Code orchestration)

**Date:** 2026-05-19
**Status:** Draft for review
**Supersedes / amends:** `docs/superpowers/specs/2026-05-19-signal-convo-brain-design.md` (only the LLM-execution path; data model + page schema unchanged)

## Goal

Build a Amélie-class brain end-to-end from inside a Claude Code session, with no `ANTHROPIC_API_KEY` and no outbound Anthropic SDK calls. The user runs one entry point (`signal-brain:build` skill, or one CLI invocation that delegates to the agent) and walks away with a fully built brain: msg_index, bursts, chunks, arcs, wiki pages, deterministic + lateral links, lint report.

Non-goal: removing Python. Python keeps doing deterministic work; only LLM calls move into the agent.

## Current state — where the SDK is used today

Four call sites in `scripts/signal_brain/`:

| Call site | Function | What it does | Call count |
|---|---|---|---|
| `tagging.py::tag_bursts` | `llm.complete_json` | Tags each burst with 1-3 topics, primary, one-sentence summary | 1 per uncached burst |
| `wiki/build.py::build_wiki` (via `wiki/{people,concepts,positions,arcs,cross}.py`) | each generator calls `llm.complete` or `llm.complete_json` once | Synthesizes one page body | 1 per page |
| `linking.py::run_stage2` | `llm.complete_json` | Proposes lateral wiki links | 1 per page |
| `evaluators.py::evaluate_bursts` | `llm.complete_json` | Judges burst boundaries | 1 per sampled boundary |

`scripts/signal_brain/llm.py` is the only place that imports `anthropic`. Everything else is deterministic Python.

## Target architecture — C from the brainstorm

Three layers, with explicit boundaries:

1. **Deterministic Python (unchanged or close to it).** `msg_index`, `bursts`, `arcs`, `manifest`, citation parse/resolve, schema validators, deterministic linking (Stage 1), lint. Runs from the agent via `Bash` tool calls into the `signal-brain` CLI.
2. **Worklist contract (new).** A small JSON-Lines format the Python pipeline emits when it needs LLM work done, and that the agent reads/writes back. One file per stage. No long-running Python process: each Python invocation does its deterministic work, then either consumes existing responses or emits a worklist and returns.
3. **Orchestrator skill (new).** A Claude Code skill `signal-brain:build` whose body tells the agent how to drive the pipeline: run CLI step → read worklist → fan out subagents → write responses → run next CLI step. The agent is the loop driver; Python provides idempotent steps.

```
┌─────────────────────────────────────────────┐
│ signal-brain:build (skill, this agent)      │
│  ├─ Bash: signal-brain ingest --plan ...    │ ──┐ deterministic L1+L2b
│  ├─ Reads data/tagging.todo.jsonl           │   │ Python — no LLM
│  ├─ Fan-out subagents (N tagging jobs)      │   │
│  ├─ Writes data/tagging.done.jsonl          │   │
│  ├─ Bash: signal-brain ingest --finalize    │ ──┘
│  ├─ Bash: signal-brain build-wiki --plan    │ ──┐ same shape:
│  ├─ Reads data/synthesis.todo.jsonl         │   │ plan → fan-out → finalize
│  ├─ Fan-out subagents (M page jobs)         │   │
│  ├─ Writes data/synthesis.done.jsonl        │   │
│  ├─ Bash: signal-brain build-wiki --finalize│ ──┘
│  ├─ Bash: signal-brain link --stage 1       │ deterministic
│  ├─ Bash: signal-brain link --stage 2 --plan│ ──┐ same shape
│  ├─ Fan-out subagents (P linking jobs)      │   │
│  └─ Bash: signal-brain link --stage 2 --fin │ ──┘
│  └─ Bash: signal-brain lint                 │ deterministic
└─────────────────────────────────────────────┘
```

## Detailed design

### 1. Worklist contract

Each stage that previously called the LLM emits a single JSONL **todo** file. The agent processes it and writes a JSONL **done** file with the same `job_id`s. The Python finalize step reads the done file and writes the durable output (chunks.jsonl, page md files, link_graph.jsonl).

**Todo row schema (uniform across stages):**
```json
{
  "job_id": "<stable-content-hash>",
  "stage": "tagging" | "synthesis" | "lateral-link" | "evaluate-bursts",
  "kind": "burst" | "page-person" | "page-concept" | "page-position" | "page-arc" | "page-cross" | "page-link" | "boundary",
  "system_prompt": "...",
  "user_prompt": "...",
  "response_schema": { "type": "object", "required": [...], "...": "..." },
  "context": { ... stage-specific metadata used at finalize ... }
}
```

**Done row schema:**
```json
{
  "job_id": "...",
  "response": { ... parsed JSON matching response_schema ... },
  "model": "subagent",  // informational; not load-bearing
  "elapsed_s": 12.3
}
```

`job_id` is a stable hash of `(stage, kind, system_prompt, user_prompt)` so reruns are idempotent: an existing done row with the same `job_id` skips work. (This subsumes the current per-burst `burst_content_hash` cache.)

**Response is always a JSON object.** Stages whose LLM output is markdown (wiki page synthesis: `wiki/{people,concepts,positions,arcs,cross}.py`) wrap the body as `{"body": "<markdown>"}`. This keeps the worker contract uniform: every subagent returns one JSON object matching a schema, and the orchestrator parses with `json.loads`. Wiki finalize then extracts `response["body"]`, attaches the planned frontmatter, and runs `validate_page(page_type, fm, body)` before writing to disk.

### 2. Python changes

**Delete:** `scripts/signal_brain/llm.py` (Anthropic SDK wrapper), `anthropic` from `pyproject.toml` runtime deps (keep in `[dev]` only if any test still wants to mock it; otherwise remove).

**Replace:** every `llm.complete_json(...)` call site becomes one of:
- `worklist_emit(todo_path, system, user, schema, job_id, context)` — writes a todo row, returns `None`.
- `worklist_consume(done_path, job_id) → dict | None` — reads response for a job_id if present.

**Add `--plan` / `--finalize` to each CLI command that used to call LLM:**

| Command | `--plan` | `--finalize` |
|---|---|---|
| `signal-brain ingest` | Build msg_index, bursts. For each burst with no cached chunk, emit a tagging todo row. Skip arcs (they need chunks). Exit. | Read `tagging.done.jsonl`, write `chunks.jsonl`, then detect arcs and write `arcs.jsonl` + manifest. |
| `signal-brain build-wiki` | Run `plan_pages`; for each page, emit a synthesis todo row. Exit. | Read `synthesis.done.jsonl`, validate each against `wiki/schemas.py`, write `<wiki_dir>/<sub>/<slug>.md`. |
| `signal-brain link --stage 2` | Run `_scan_pages`; for each page, emit a lateral-link todo row. Exit. | Read `link.done.jsonl`, merge into Stage 1 graph, write `data/link_graph.jsonl` and update `## Related` blocks. |
| `signal-brain evaluate-bursts` | Sample N boundaries; emit todo rows. Exit. | Read `eval.done.jsonl`, aggregate counts, print JSON. |

No `--plan` / `--finalize` flag means **legacy mode**: error out with a clear message ("set `ANTHROPIC_API_KEY` or use `signal-brain:build` skill"). Keeping a single `ingest`-without-flags that does it all is appealing but would re-introduce the API dependency by default; better to break it explicitly so the orchestrator skill is the only happy path.

**Worklist module (new):** `scripts/signal_brain/worklist.py`.

```python
# Public surface (signatures only)
def emit(todo_path: Path, *, stage: str, kind: str,
         system: str, user: str,
         response_schema: dict, context: dict) -> str:
    """Append a todo row. Returns job_id. Idempotent: if job_id already present, no-op."""

def load_done(done_path: Path) -> dict[str, dict]:
    """job_id -> response dict. Returns {} if file missing."""

def stable_job_id(stage: str, kind: str, system: str, user: str) -> str:
    """sha256(stage|kind|system|user) -> first 16 hex chars."""

def validate_response(response: dict, schema: dict) -> None:
    """Raises WorklistError on schema violation."""
```

UTF-8 explicit on all reads/writes. Existing convention.

### 3. The orchestrator skill

**File:** `~/.claude/plugins/.../signal-brain/skills/build/SKILL.md` (or wherever the project ships local skills — to be confirmed during plan stage; could live at `skills/signal-brain-build/SKILL.md` in the repo and be installed via the user's skill loader).

**Skill description (frontmatter):** "Build a Signal conversation brain end-to-end (L1 → wiki → links → lint) without an Anthropic API key. Use when the user says 'build the brain', 'run signal-brain', or invokes this skill directly."

**Skill body (the instructions the agent follows):**

1. Resolve source (or ask if multiple, but here we trust user gave it).
2. Run `signal-brain ingest --plan --source <s>`. Read `brain/<s>/data/tagging.todo.jsonl`.
3. **Fan-out tagging.** Dispatch one `general-purpose` subagent per todo row, up to `--max-parallel N` (default 30). Each subagent gets:
   - The system prompt and user prompt verbatim.
   - Instruction: "Return ONLY a JSON object matching this schema: <schema>. No prose, no markdown fences."
   - The subagent calls no tools; it just returns text.
   - Orchestrator parses the response, validates against schema, writes a done row.
4. On schema failure: retry once in a fresh subagent with one additional line ("Your previous response failed schema validation: <error>. Return strict JSON."). If still failing, write a `tagging.failed.jsonl` row and continue. Surface failures at the end.
5. Run `signal-brain ingest --finalize --source <s>`.
6. Run `signal-brain build-wiki --plan`, fan-out synthesis subagents, finalize. Same pattern.
7. Run `signal-brain link --stage 1` (deterministic).
8. Run `signal-brain link --stage 2 --plan`, fan-out link subagents, finalize.
9. Run `signal-brain lint`.
10. Print a one-screen summary: pages written, bursts, arcs, lint findings count, any failed jobs.

The fan-out at step 3/6/8 uses the harness's parallel Agent invocations (one tool-use block, multiple `Agent` calls). For N>30 work the skill batches them sequentially.

### 4. Subagent prompt shape

Each subagent receives a **self-contained** prompt with three parts:

```
SYSTEM:
{system_prompt from todo row}

You are running as a JSON-emitting worker. Do not call tools. Return ONLY the JSON object described below — no prose, no markdown fences, no commentary.

Response schema:
{response_schema from todo row, rendered as JSON Schema or a short example}

USER:
{user_prompt from todo row}
```

The agent dispatches with `subagent_type: "general-purpose"`, `description: "Tag burst B0017"` (or similar 3-5 word label per `Agent` tool docs). The subagent's final message is the JSON response. Orchestrator parses with `json.loads(...)`, stripping a leading ``` ```json ``` fence if present (same logic as today's `complete_json`).

### 5. Caching & idempotence

`job_id = sha256(stage|kind|system|user)[:16]`. Reruns:

1. `signal-brain build` re-plans: emits the same todo rows (same job_ids).
2. Orchestrator reads `*.done.jsonl` first; for any `job_id` already present, skip the subagent.
3. Only **new** or **content-changed** jobs get a subagent.

This subsumes today's `burst_content_hash` cache (for tagging) and gives the same incremental property for wiki pages and links — which today have no caching at all (item 7 in `KNOWN_ISSUES.md`).

To invalidate a stage's cache: delete `<stage>.done.jsonl`. To invalidate one job: remove its row.

### 6. Schema enforcement (load-bearing)

`wiki/schemas.py` already exists and is the gate. Under this design:

- Tagging done rows: validated against the inline `response_schema` (topics, primary, summary fields).
- Synthesis done rows: validated as "is this valid markdown body that, when combined with the planned frontmatter, passes `validate_page(page_type, fm, body)`?" The finalize step does the full schema check before writing the .md file.
- Link done rows: validated against `{"links": ["[[...]]", ...]}`, capped at 6 entries, self-links stripped.
- Eval done rows: `{"verdict": "natural|should-merge|should-split-elsewhere", "rationale": str}`.

Validation failures during finalize: write a `<stage>.failed.jsonl` row, write a placeholder page (for synthesis), and continue. Lint will pick up the placeholder. **Failures are loud at end-of-build, not silent.** This is an improvement over today's `llm.py` silent retries.

### 7. CLI surface — final state

```
signal-brain list-sources

# Deterministic (no agent needed):
signal-brain build-index   --source <s>
signal-brain link          --source <s> --stage 1
signal-brain lint          --source <s>

# Plan/finalize pairs (agent runs between them):
signal-brain ingest        --plan|--finalize --source <s>
signal-brain build-wiki    --plan|--finalize --source <s>
signal-brain link          --stage 2 --plan|--finalize --source <s>
signal-brain evaluate-bursts --plan|--finalize --source <s> --sample-size N

# Convenience (calls the skill via the orchestrator):
# — invoked as the Skill `signal-brain:build` from inside Claude Code
```

The bare `signal-brain ingest` / `build-wiki` / `link --stage 2` / `evaluate-bursts` commands without flags are removed (or left as friendly errors pointing at `--plan` and the skill).

### 8. File layout under `brain/<source>/`

```
brain/<source>/
├── data/
│   ├── msg_index.jsonl              # (unchanged)
│   ├── bursts.jsonl                 # (unchanged)
│   ├── chunks.jsonl                 # (unchanged)
│   ├── arcs.jsonl                   # (unchanged)
│   ├── manifest.json                # (unchanged)
│   ├── link_graph.jsonl             # (unchanged)
│   ├── tagging.todo.jsonl           # NEW — input to tagging subagents
│   ├── tagging.done.jsonl           # NEW — outputs from tagging subagents
│   ├── tagging.failed.jsonl         # NEW — failures (absent if none)
│   ├── synthesis.todo.jsonl         # NEW
│   ├── synthesis.done.jsonl         # NEW
│   ├── synthesis.failed.jsonl       # NEW
│   ├── link.todo.jsonl              # NEW
│   ├── link.done.jsonl              # NEW
│   └── link.failed.jsonl            # NEW
├── people/  concepts/  positions/  arcs/  cross/
├── index.md
├── log.md
└── lint-report.md
```

`*.todo.jsonl` and `*.failed.jsonl` are debugging artifacts; `*.done.jsonl` is the cache. None should be committed (already gitignored under `brain/<source>/`).

## Failure modes

| Failure | Today | Under this design |
|---|---|---|
| API rate-limited | Retry with exponential backoff in `llm.py` | N/A (no API) |
| Subagent returns malformed JSON | N/A | One retry; on second failure, written to `*.failed.jsonl`, surfaced at end of build |
| Subagent times out | N/A | Treated as malformed; retried once |
| Schema validation fails | `SchemaError` raised, page not written | Same — but written to `*.failed.jsonl` with the offending response, build continues |
| Disk full mid-write | Crash | Same; restartable because done.jsonl is append-only and job_ids dedupe |
| Agent context exhausted mid-run | N/A | Subagents have their own contexts; orchestrator only handles JSON files. Worst case: orchestrator dies, user re-runs the skill, done.jsonl picks up where it left off. |

## Migration plan

Four task-sized chunks, each independently shippable:

1. **Worklist module + Python refactor of `tagging.py`.** Add `worklist.py`. Refactor `tag_bursts` to call `worklist.emit` instead of `llm.complete_json`. Add `ingest --plan` and `ingest --finalize` to CLI. Tests: feed a fake done.jsonl into finalize, verify chunks.jsonl identical to today's output for the mini fixture.
2. **Refactor wiki page generators.** Same pattern, one generator at a time (person → concept → position → arc → cross). Each generator's prompt builder stays the same; the function returns `(system, user, schema)` instead of calling the LLM. `build_wiki` emits todos and finalizes from done.jsonl.
3. **Refactor `linking.run_stage2` and `evaluators.evaluate_bursts`.** Same pattern.
4. **Ship the orchestrator skill.** Write `signal-brain:build` skill. Manual end-to-end test on the mini fixture, then on Amélie.

Until step 4 ships, the system is **unusable** end-to-end without a wrapper. Steps 1-3 land behind `--plan`/`--finalize` flags, with no legacy `ingest`-as-one-shot path. Acceptable because the user is the only consumer and is driving this redesign.

After all four ship: delete `llm.py`, remove `anthropic` from runtime deps, update `README.md` and `CLAUDE.md` to remove the `ANTHROPIC_API_KEY` line.

## Tests

The existing test suite has 66 tests using a mocked `LLMClient`. Migration:

- Tests that mock `llm.complete_json(...)` become tests that feed pre-baked done.jsonl rows into the finalize step. Same assertions on output files. The mock surface shrinks from "an LLM" to "a JSON file."
- New tests:
  - `test_worklist.py`: emit/load/dedupe by job_id.
  - `test_worklist_schema.py`: validate_response happy/sad path.
  - `test_ingest_plan_finalize.py`: round-trip through todo.jsonl → done.jsonl → chunks.jsonl; verify byte-for-byte equivalence with today's output for the mini fixture.
  - `test_build_wiki_plan_finalize.py`: same for one page-type.
- Skill cannot be unit-tested from Python. Manual smoke test on the mini fixture.

Targeting: 66 → ~75 tests, all passing offline, no API key.

## Out of scope

- Parallelism limits beyond the subagent fan-out cap. (No semaphore on the Python side.)
- Streaming subagent output. (Subagents return one final message; that's enough.)
- Switching synthesis to a different model. (Quality is "whatever the user's Claude Code session has.")
- KNOWN_ISSUES.md items #1, #3, #4. Orthogonal; tackle separately.
- A "resume from N% complete" UI. Re-run the skill; idempotence handles it.

## §9 — Skill distribution across runtimes (Claude Code + Codex)

The orchestrator skill must be discoverable from both runtimes the user works in: Claude Code and OpenAI Codex. Both runtimes happen to use the same skill format and the same `<root>/skills/<name>/SKILL.md` convention; they only differ in where `<root>` lives. So one canonical skill directory in the repo, symlinked into both runtime homes, is enough.

### Skill format (shared)

```
skills/signal-brain-build/
├── SKILL.md          # YAML frontmatter (name, description, optional user-invocable) + markdown body
└── (optional) references/   # if we split the body
```

Both Claude Code (`~/.claude/skills/<name>/`) and Codex (`~/.codex/skills/<name>/`) read SKILL.md the same way: frontmatter declares triggers, body is the instructions the agent follows. Examples already on this machine:
- `~/.codex/skills/cloudflare-deploy/SKILL.md` (Codex)
- `~/.claude/skills/slack-block-kit-designer -> ../../.agents/skills/slack-block-kit-designer` (Claude, already using a symlink)

### Install via symbolic symlinks (not hardlinks)

The repo ships the canonical skill at `signal-convo/skills/signal-brain-build/`. An install script creates **symbolic** symlinks (not hardlinks — hardlinks won't span filesystems and break on directories anyway) into both runtime homes.

```
~/.claude/skills/signal-brain-build  ──symlink──▶  $PWD/skills/signal-brain-build
~/.codex/skills/signal-brain-build   ──symlink──▶  $PWD/skills/signal-brain-build
```

This means: edits to `skills/signal-brain-build/SKILL.md` in the repo are picked up by both runtimes immediately, with no copy step. Git ownership stays in the repo.

### Install script

`scripts/install-skills.sh`:

```bash
#!/usr/bin/env bash
# Symlink repo skills into Claude Code and Codex skill directories.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SKILLS_SRC="$REPO_ROOT/skills"

for runtime_dir in "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  mkdir -p "$runtime_dir"
  for skill_path in "$SKILLS_SRC"/*/; do
    name="$(basename "$skill_path")"
    target="$runtime_dir/$name"
    if [ -L "$target" ]; then
      rm "$target"            # replace existing symlink
    elif [ -e "$target" ]; then
      echo "Skipping $target (exists and is not a symlink)" >&2
      continue
    fi
    ln -s "$skill_path%/}" "$target"   # symbolic, absolute
    echo "Linked $target -> $skill_path"
  done
done
```

Notes:
- `ln -s` (symbolic) — explicit per the user's requirement. No `-P` (hardlink) flag.
- Absolute target path so the symlink resolves regardless of caller cwd.
- If a non-symlink already exists at the target, skip it (don't clobber user files).
- Idempotent: re-running is safe; existing symlinks are replaced.

### Codex subagent requirement

Codex requires `multi_agent = true` to enable `spawn_agent`/`wait_agent` (per `using-superpowers/references/codex-tools.md`). The README adds a one-liner instructing the user to add this to `~/.codex/config.toml` once:

```toml
[features]
multi_agent = true
```

The skill body uses Claude Code's `Agent` tool semantics but the codex-tools reference provides the equivalents; Codex picks up the mapping via its own `using-superpowers` skill at session start. No further action needed in the skill body — same instructions work on both.

### What the skill body looks like (tool-neutral)

The skill body refers to "dispatch a subagent" without naming a specific tool. Each runtime translates per its tool-mapping reference:

| Skill body says | Claude Code | Codex |
|---|---|---|
| "dispatch one subagent per row" | `Agent` tool call | `spawn_agent` call |
| "wait for completion, parse JSON" | (Agent returns final message) | `wait_agent` then `close_agent` |
| "update progress" | `TaskUpdate` | `update_plan` |

This keeps the skill source single-canonical. Tool translation is the runtime's job, not the skill's.

### Acceptance

- After running `bash scripts/install-skills.sh` once on a fresh machine, `signal-brain:build` shows up in both `claude` and `codex` skill listings.
- Editing `skills/signal-brain-build/SKILL.md` in the repo and saving is reflected in both runtimes on next invocation (no re-install needed).
- `git status` after install is clean (the symlinks live in the user's home, not in the repo).

## Open questions for review

1. ~~**Skill location.**~~ Resolved: repo-local at `skills/signal-brain-build/`, symlinked into both runtime homes via `scripts/install-skills.sh`. See §9.
2. **Subagent type.** `general-purpose` (full tool access) vs a custom narrow type with no tools? Custom would be safer (subagent can't accidentally write files) but adds setup overhead. **Default: `general-purpose` with explicit "do not call tools" instruction in the prompt.**
3. **Failed-job UX.** Pass on failure (current proposal) vs hard-fail the build? Soft-fail makes sense for synthesis (a missing page is recoverable) but maybe not for tagging (all downstream depends on it). **Default: soft-fail with end-of-build summary; user re-runs the skill to retry just the failed jobs.**

## Acceptance criteria

- [ ] `ANTHROPIC_API_KEY` is unset in env. Running `signal-brain:build` skill on Amélie produces a full brain: `data/{msg_index,bursts,chunks,arcs}.jsonl`, all wiki subdirectories populated, `index.md` non-empty, `log.md` updated, `lint-report.md` present.
- [ ] Re-running the skill on the same source with no changes finishes in <30 seconds (all cached; no subagent dispatches).
- [ ] Re-running after a content change in the source re-tags only the affected bursts and re-synthesizes only the affected pages.
- [ ] `pip install -e .` works without `anthropic` in runtime deps.
- [ ] All 66+ existing tests pass; new tests for worklist + plan/finalize pass.
- [ ] `README.md` and `CLAUDE.md` no longer mention `ANTHROPIC_API_KEY`.

---
name: signal-brain-build
description: >
  Build a Signal conversation brain end-to-end (ingest → wiki → links → lint)
  with no Anthropic API key. Drives the local `signal-brain` CLI through
  plan/finalize phases and dispatches subagents for the LLM-shaped work
  (per-burst tagging, wiki page synthesis, lateral linking). Use when the user
  says "build the brain", "regenerate the brain", "run signal-brain", or
  invokes this skill by name.
user-invocable: true
---

# signal-brain-build

You will drive the `signal-brain` pipeline end-to-end. The Python CLI does all deterministic work (msg_index, bursts, arcs, schemas, citations, lint). The LLM-shaped work is done by **you, via subagents**: one subagent per burst for tagging, one per wiki page for synthesis, one per page for lateral linking. There is no `ANTHROPIC_API_KEY` and no outbound API call.

The contract is file-based: each `--plan` invocation writes a `*.todo.jsonl` file, you fan out subagents to produce a matching `*.done.jsonl`, then `--finalize` consumes it. Re-runs are idempotent — `job_id`s are content-hashed, so unchanged work is skipped automatically.

## Prerequisites

- `cd` is the repo root (where `pyproject.toml` lives).
- `.venv` exists with `pip install -e ".[dev]"` already run. If not, run `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"` first.
- A conversation export exists under `out/<source>/data.json`. Use `signal-brain list-sources` if unsure.
- **On Codex:** `~/.codex/config.toml` must contain `[features]\nmulti_agent = true` so `spawn_agent`/`wait_agent` are available. Tell the user if it's missing.

## Step-by-step

Use a task list (TodoWrite / update_plan) to track these. Mark each step `in_progress` when you start and `completed` when its CLI command exits with stats. Note that step 2 is a **loop** (`ingest --plan` + fan-out) with a `2a` taxonomy sub-step; track it as one task and leave it `in_progress` until the loop converges.

### 1. Resolve the source

If the user didn't specify a source:

```bash
source .venv/bin/activate
signal-brain list-sources
```

If there's exactly one entry, use it. If multiple, surface the list and ask the user once. After this step, you have `SRC` (the source name, e.g. `SébastienBéal`).

### 2. Ingest — plan loop

`signal-brain ingest --plan` is self-progressing. Run it, inspect the printed
stats, and act on them in a loop until no stage is pending:

```bash
signal-brain ingest --plan --source "$SRC"
```

| Stat in the output | What to do next |
|---|---|
| `taxonomy_pending: true` (with `taxonomy_todos: 1`) | Do **2a (taxonomy fan-out)**, then re-run `ingest --plan`. |
| `taxonomy_pending: false`, `tagging_todos > 0` | Do **3 (tagging fan-out)**, then **4 (ingest --finalize)**. |
| `taxonomy_pending: false`, `tagging_todos: 0` | Nothing to tag (all bursts cached). Skip to **4 (ingest --finalize)**. |

Re-run `signal-brain ingest --plan --source "$SRC"` after each fan-out. The loop
terminates when `taxonomy_pending` is false. Normally this is a two-iteration
loop: iteration 1 emits the taxonomy todo, iteration 2 (after taxonomy fan-out)
emits the tagging todos.

**Guard against a stuck loop:** if `ingest --plan` returns `taxonomy_pending:
true` again *after* you have already completed a taxonomy fan-out, the taxonomy
subagent is producing an unusable result (e.g. an empty taxonomy, which the
pipeline rejects). Do not loop a third time — stop, tell the user the taxonomy
stage is not converging, and surface the contents of `data/taxonomy.failed.jsonl`
(if present) or the latest `data/taxonomy.done.jsonl` row.

#### 2a. Taxonomy fan-out

Read `brain/$SRC/data/taxonomy.todo.jsonl`. It contains exactly **one** row.
Dispatch a single subagent using the same prompt template as tagging (see Step 3).
Response schema:

```
required keys: ["taxonomy", "notes"]
types:         {"taxonomy": "list", "notes": "str"}
```

The taxonomy prompt embeds the full conversation, so it is a heavier call than a
per-burst tag — allow it more time. On parse/schema failure, retry once exactly
as for tagging; on a second failure, append to `brain/$SRC/data/taxonomy.failed.jsonl`
and STOP — without a taxonomy, tagging produces uncontrolled slugs and the wiki
regresses. Do not proceed to tagging.

On success, append one row to `brain/$SRC/data/taxonomy.done.jsonl`:

```json
{"job_id": "<from todo>", "response": <parsed dict>, "model": "subagent"}
```

Then go back to **Step 2** and re-run `ingest --plan`.

### 3. Tagging fan-out

Read `brain/$SRC/data/tagging.todo.jsonl`. For each row, dispatch one subagent. Cap concurrent dispatches at 30; batch sequentially beyond that. This step is reached from the Step 2 loop once `taxonomy_pending` is false and `tagging_todos > 0`.

**Subagent prompt template** — render this verbatim with the row's `system_prompt`, `user_prompt`, and `response_schema`:

```
SYSTEM:
{system_prompt}

You are a JSON-emitting worker. Do not call any tools. Your entire response
must be one JSON object matching this schema. No prose, no markdown fences,
no commentary before or after.

Schema:
  required keys: {response_schema.required}
  types:         {response_schema.types}

USER:
{user_prompt}
```

Dispatch with a short description like `"Tag burst <burst_id>"`. The subagent's final message text is the JSON response.

For each subagent reply:
1. Pass through `signal_brain.worklist.parse_subagent_response` (strips optional ```json fences, json.loads).
2. Validate with `signal_brain.worklist.validate_response(resp, schema)`.
3. On success, append one row to `brain/$SRC/data/tagging.done.jsonl`:
   ```json
   {"job_id": "<from todo>", "response": <parsed dict>, "model": "subagent"}
   ```
4. On failure (parse error or schema violation): retry **once** in a fresh subagent, adding one line to the prompt: `"Your previous response failed validation: <error>. Return strict JSON, no fences, no prose."` If the retry also fails, append to `brain/$SRC/data/tagging.failed.jsonl` with `{job_id, error, last_response_snippet}` and continue. Do not abort the whole pipeline for one failure.

When all rows are processed (or accounted for in failed.jsonl), continue.

### 4. Ingest — finalize phase

```bash
signal-brain ingest --finalize --source "$SRC"
```

This reads tagging.done, writes `chunks.jsonl`, detects arcs, updates manifest. If `stats.tagging.missing` is non-empty, tell the user which bursts have no done row and stop — don't proceed to wiki synthesis on incomplete data.

### 5. Build wiki — plan phase

```bash
signal-brain build-wiki --plan --source "$SRC"
```

Writes `brain/$SRC/data/synthesis.todo.jsonl`. Read it.

### 6. Synthesis fan-out

Same pattern as tagging. **Key difference:** wiki page bodies are markdown wrapped as `{"body": "<markdown>"}`. The schema for every synthesis todo is `{"required": ["body"], "types": {"body": "str"}}`.

The body must follow strict section requirements (see the system prompt — it lists the required `## headings` for each page type). The Python finalize step validates with `wiki/schemas.py::validate_page` and rejects any body missing a required section. So tell each subagent to follow the section list **exactly**, in order.

Cap concurrent dispatches at 15 here (page synthesis is heavier than tagging).

### 7. Build wiki — finalize phase

```bash
signal-brain build-wiki --finalize --source "$SRC"
```

Writes the .md files. Schema violations end up in `synthesis.failed.jsonl`. Read it if present and surface to the user.

### 8. Build the index

```bash
signal-brain build-index --source "$SRC"
```

Deterministic. Populates `brain/$SRC/index.md`.

### 9. Stage 1 linking (deterministic)

```bash
signal-brain link --stage 1 --source "$SRC"
```

### 10. Stage 2 linking — plan phase

```bash
signal-brain link --stage 2 --plan --source "$SRC"
```

Writes `brain/$SRC/data/link.todo.jsonl`. Read it.

### 11. Lateral-link fan-out

Same pattern. Response schema: `{"required": ["links"], "types": {"links": "list"}}`. Each link is a string like `[[concepts/foo]]` or `[[positions/x--y]]`. Cap concurrent dispatches at 15.

### 12. Stage 2 linking — finalize phase

```bash
signal-brain link --stage 2 --finalize --source "$SRC"
```

Merges with Stage 1, writes `link_graph.jsonl`, updates `## Related` blocks. Invalid responses go to `link.failed.jsonl`.

### 13. Lint

```bash
signal-brain lint --source "$SRC"
```

Writes `brain/$SRC/lint-report.md`.

### 14. Summary

Print one screen to the user:

- Source name
- Bursts / arcs / pages written
- Tagging missing/invalid counts (if any)
- Synthesis failed count (if any)
- Stage 2 link failed count (if any)
- Path to `brain/$SRC/index.md` and `brain/$SRC/lint-report.md`
- Any deferred work the user should re-run the skill for

If anything went into a `*.failed.jsonl`, point at the file and offer a re-run.

## Re-running the skill

Idempotent end-to-end. Re-running picks up where it left off:

- A cached taxonomy (`taxonomy.done.jsonl` present) means iteration 1 of the Step 2 loop already returns `taxonomy_pending: false` — the loop runs once and the taxonomy fan-out (2a) is skipped.
- Cached bursts (content-hash match against the manifest) skip the tagging fan-out (step 3): `ingest --plan` returns `tagging_todos: 0` and you go straight to step 4.
- `done.jsonl` rows are kept; only missing/invalid jobs get re-dispatched.
- Wiki pages already on disk are not re-synthesized unless their planned content changed (the spec's hash-based plan dedupes them).
- Stage 1 links are deterministic — fast re-run.

To force a clean rebuild of one stage: delete the corresponding `*.done.jsonl` (and `*.failed.jsonl` if present), then re-run.

## Failure modes

| What happened | What to do |
|---|---|
| Subagent returned non-JSON | Retry once with the "strict JSON" reminder. Second failure → `failed.jsonl`, continue. |
| Subagent returned wrong schema | Same as above. |
| Python CLI exits non-zero | Read stderr, surface to user. Do not auto-retry the CLI. |
| `tagging.missing` non-empty after finalize | Stop. Tell the user which bursts; do not proceed. |
| `ingest --plan` still `taxonomy_pending: true` after a taxonomy fan-out | Stuck loop. Stop after iteration 2 — do not fan out a third time. Surface `taxonomy.failed.jsonl` or the latest `taxonomy.done.jsonl` row. |
| `synthesis.failed.jsonl` non-empty | Continue (per-page is recoverable). Surface in the summary. |
| User's session is interrupted mid-fan-out | On re-run, the orchestrator sees existing done.jsonl rows and skips them. |

## Tool name mapping

This skill uses runtime-agnostic language ("dispatch a subagent"). Translate per your runtime:

| This skill says | Claude Code | Codex |
|---|---|---|
| dispatch a subagent | `Agent` (single tool call) | `spawn_agent` |
| wait for the subagent | (Agent returns final message) | `wait_agent` then `close_agent` |
| update the task list | `TaskUpdate` | `update_plan` |
| read/write a file | `Read` / `Write` / `Edit` | native file tools |
| run a shell command | `Bash` | native shell |

If you're unsure, see `superpowers:using-superpowers` references (`copilot-tools.md`, `codex-tools.md`).

## Don't

- Don't call any Anthropic API directly. The point of this skill is that you don't need one.
- Don't hand-edit wiki pages or `## Related` blocks. The link pass owns those.
- Don't skip the schema validation step. The wiki only stays usable because every page satisfies `wiki/schemas.py`.
- Don't commit anything under `brain/<source>/`. It's gitignored and per-developer.

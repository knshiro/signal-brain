# Agent guide — Signal Conversation Brain (project root)

This file (mirrored as `CLAUDE.md`) tells an agent working **on this codebase** how to navigate, develop, test, and extend it. For instructions on consuming a single conversation's brain, see `brain/<source>/AGENTS.md` instead.

## What the project is

A Python tool that turns a Signal conversation export into a Karpathy-style wiki "brain". Each conversation becomes one self-contained folder of markdown pages with citations resolving back to exact messages. See `README.md` for the public-facing overview.

The LLM-shaped work (per-burst tagging, wiki page synthesis, lateral linking, burst evaluation) is done by **the surrounding agent runtime via subagents**, not by direct Anthropic SDK calls. The Python pipeline emits `*.todo.jsonl` worklists in `--plan` mode and consumes `*.done.jsonl` files in `--finalize` mode. There is **no `ANTHROPIC_API_KEY`** anywhere in this codebase.

## Where things live

```
scripts/signal_brain/   # Python package
  msg_index.py          # stable message IDs
  bursts.py             # L1 time-gap clustering + content hashing
  manifest.py           # incremental-ingest state
  citations.py          # parse/resolve [Bnnnn#mN] citations
  worklist.py           # plan/finalize todo/done JSONL contract + schema validator
  tagging.py            # L2a per-burst topic tagger (emits + finalizes todos)
  arcs.py               # L2b consecutive-topic arc detection (deterministic)
  ingest.py             # split into run_ingest_plan and run_ingest_finalize
  sources.py            # source-conversation discovery, slugify
  indexing.py           # build_index, bootstrap_brain_root, append_log
  linking.py            # Stage 1 deterministic + Stage 2 plan/finalize
  lint.py               # health checks
  evaluators.py         # burst evaluator (plan/finalize)
  cli.py                # signal-brain CLI (Click) — every LLM stage is --plan/--finalize
  wiki/
    schemas.py          # frontmatter + section validators
    people.py concepts.py positions.py arcs.py cross.py
                        # each exposes build_*_prompts + render_*_page (no LLM inside)
    build.py            # plan_pages + build_wiki_plan + build_wiki_finalize

scripts/tests/          # pytest suite (all offline; no API key)
  conftest.py           # shared fixtures: mini_messages, tmp_data_dir, tmp_wiki_dir
  fixtures/mini_data.json
  test_worklist.py      # the new contract
  test_*_plan_finalize.py — round-trip tests per stage

scripts/install-skills.sh  # symlinks skills/ into ~/.claude/skills and ~/.codex/skills

skills/
  signal-brain-build/   # orchestrator skill (Claude Code + Codex; runtime-agnostic body)
    SKILL.md

docs/superpowers/specs/  # design specs (original + no-API-key redesign)
docs/superpowers/plans/  # implementation plans
out/<source>/            # raw sigexport input (immutable)
brain/                   # gitignored except AGENTS.md and CLAUDE.md at the root
  AGENTS.md              # canonical agent guide for reading any source (committed)
  CLAUDE.md              # mirror of AGENTS.md
  <source>/              # per-source artifact (gitignored, regenerated locally)
    data/                # msg_index, bursts, chunks, arcs, manifest, link_graph,
                         # plus *.todo.jsonl / *.done.jsonl / *.failed.jsonl
    people/ concepts/ positions/ arcs/ cross/
    index.md log.md lint-report.md
KNOWN_ISSUES.md          # carry-forward items from per-task reviews
config.toml              # tunable knobs (bursts, arcs, me identity, tagging priming)
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Make the orchestrator skill visible to Claude Code and Codex
bash scripts/install-skills.sh
```

No API key. On Codex, also add `[features]\nmulti_agent = true` to `~/.codex/config.toml` so `spawn_agent`/`wait_agent` are available to the skill.

## Run tests before and after every change

```bash
source .venv/bin/activate
pytest -q       # full suite (all offline; no API key needed)
```

Tests should always be green. If you change a public function signature, update its tests in the same commit.

## Standing conventions

These are non-negotiable. Past review cycles enforced them; future code must follow.

- **UTF-8 explicit on every file I/O.** All `Path.read_text(...)` and `Path.write_text(...)` calls include `encoding="utf-8"`. The codebase has UTF-8 sender labels (`Amélie`) and French source content; default encoding is unreliable across platforms.
- **Operator-identity scrubbing.** `config.toml [me].real_names` is a per-developer list of plain-string patterns (e.g., `["Ugo", "Ugo Bataillard"]`) that are scrubbed from message bodies and quoted text during ingest, replaced with `[me].name` (or its first token, for single-token patterns). Word-boundary anchored, case-insensitive, case-preserved. The committed default is `[]`; populate it locally and don't commit your real names. Without it, the other party's references to you by your real name leak into `brain/<src>/` and break the pseudonym.
- **Python 3.11+ type hints.** Use built-in generics (`list[dict]`, `dict[str, int]`, `str | None`) — no `typing.List`/`Optional`.
- **Slug rules.** Lowercase ASCII, kebab-case, no diacritics. `slugify("BjörkGuðmundsdóttir") == "bjorkgudmundsdottir"`. See `scripts/signal_brain/sources.py`.
- **Citation format.** `[Bnnnn#mN]` where `Bnnnn` is a 4-digit zero-padded burst id and `mN` is the 1-indexed position of the message inside that burst's `msg_ids`. Always cite; lint catches unresolved citations.
- **Wiki content is English.** Quoted source material is preserved verbatim in French inside citations.
- **`## Related` section in wiki pages is auto-maintained.** Only the link pass writes it; never hand-edit.
- **Content-neutral defaults.** The topic tagger and slug examples carry no conversation-specific terms. The default system prompt describes only "a Signal conversation between two people". Per-thread priming lives in `config.toml` under `[tagging]` (`description` and `seed_tags`).
- **No direct LLM calls in Python.** Every LLM-shaped step goes through the `worklist.emit` / `worklist.load_done` contract. The agent runtime fills in the done file via subagents. If you find yourself reaching for an Anthropic SDK, stop — the design assumes that path is gone.

## CLI surface

Every stage that needs LLM work is **two-phase**: `--plan` writes a todo file, `--finalize` consumes a done file. Bare invocations (without a phase flag) error out — there is no legacy single-shot mode.

```
signal-brain --help
  list-sources
  ingest          --plan|--finalize  --source <name>
  build-wiki      --plan|--finalize  --source <name>
  build-index                        --source <name>          # deterministic
  link --stage 1                     --source <name>          # deterministic
  link --stage 2  --plan|--finalize  --source <name>
  lint                               --source <name>          # deterministic
  evaluate-bursts --plan|--finalize  --source <name> --sample-size <n>
```

For an end-to-end build, invoke the `signal-brain-build` skill from inside Claude Code or Codex. It runs the right CLI commands in order and fans out subagents between phases.

`--source` is optional when exactly one conversation lives under `out/`.

## TDD workflow

1. Write a failing test first.
2. Run it: `pytest scripts/tests/<your_test>.py -v` — confirm the right failure (e.g., `ModuleNotFoundError`).
3. Implement the minimal code to make it pass.
4. Run tests again — confirm green.
5. Commit. Use focused commits (`feat:`, `fix:`, `chore:`, `refactor:`).

## Where to look first

- **Adding a feature**: read the spec section it relates to, then the corresponding plan task. The plan IS the reference implementation.
- **Fixing a bug**: check `KNOWN_ISSUES.md` first — it may already be tracked. If not, add it.
- **Understanding the data flow**: `scripts/signal_brain/ingest.py` (`run_ingest_plan` / `run_ingest_finalize`) is the end-to-end backbone. `scripts/signal_brain/worklist.py` is the contract between Python and the agent.
- **Understanding wiki generation**: `scripts/signal_brain/wiki/build.py::plan_pages` decides what pages to make; `build_wiki_plan` emits synthesis todos; `build_wiki_finalize` consumes done rows and writes the .md files through the page-schema validators.
- **Understanding the orchestrator skill**: `skills/signal-brain-build/SKILL.md`. It's the runtime-agnostic body driving the pipeline.
- **Understanding agent-consumption conventions**: `brain/AGENTS.md` (mirrored as `brain/CLAUDE.md`).
- **Tuning topic tagging for a specific conversation**: set `description` and/or `seed_tags` in `config.toml`'s `[tagging]` section. The tagger is neutral when both are empty.

## Known deferred items

`KNOWN_ISSUES.md` lists ~20 items deferred from per-task code reviews. The most impactful are:

1. **L3 dirty-flag propagation absent.** Re-export doesn't flag wiki pages as needing update.
2. **Three lint checks stubbed.** Stale claims, tag synonyms, and missing concept pages always emit `(none)`.
3. **Tail-only burst re-detection absent.** Re-ingest rebuilds all bursts (cheap at 2.3k messages, expensive at scale).
4. **Linking spec drift.** Arc ↔ position is linked by shared `primary_topic` rather than burst overlap.

Tackle these before regular re-export use.

## Don't

- Never run a destructive `git` command (force push, hard reset, branch delete) without explicit user approval.
- Never commit anything under `brain/<source>/` — those directories are gitignored. Each developer regenerates the brain locally from their own exports. The only committed files under `brain/` are `brain/AGENTS.md` and `brain/CLAUDE.md`.
- Never narrow the encoding rule "just for this one read". The convention is enforced; consistency matters more than local minimization.
- Never bypass the page schema validators when writing wiki pages — they're the only thing keeping LLM output from drifting.
- Never re-introduce direct Anthropic SDK calls or an `ANTHROPIC_API_KEY` dependency. Every LLM stage must go through the worklist contract.
- Never re-introduce conversation-specific terms into production code or the default config. The codebase is intentionally generic; per-thread priming lives exclusively in `config.toml [tagging]`.

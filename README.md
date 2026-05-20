# Signal Conversation Brain

Turn a Signal conversation export into a Karpathy-style wiki "brain" that future AI agents can consume as personal memory. Each conversation becomes one self-contained folder of markdown pages (people, concepts, positions, arcs, cross-cuts) with citations resolving back to exact messages.

## What it does

Given an export from [`signal-export`](https://github.com/carderne/signal-export), this tool:

1. **L1 — Bursts.** Clusters messages by time-gap (default 60 min) into contiguous "sittings".
2. **L2 — Topics & arcs.** An LLM tags each burst with topics; consecutive same-topic bursts fuse into named debate arcs.
3. **L3 — Wiki pages.** Generates five page types backed by citations to exact messages:
   - *People* (entity pages, one per sender)
   - *Concepts* (one per topic above threshold)
   - *Positions* — `{person}--{concept}.md`, the page type unique to debate wikis
   - *Arcs* (narrative summary of each debate arc)
   - *Cross* (agreements, disagreements, rhetorical patterns, empirical pool)
4. **L4 — Indexes & links.** Builds `index.md`, append-only `log.md`, a deterministic + LLM-assisted link pass that populates each page's `## Related` section, and a `lint-report.md` for citation/orphan checks.

Output for one conversation lives at `brain/<source>/`. Multiple conversations coexist.

## Install

Requires Python 3.11 or newer. **No Anthropic API key needed** — the LLM-shaped work is done by your agent runtime (Claude Code or OpenAI Codex) via subagents.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Make the build skill available to Claude Code and Codex
bash scripts/install-skills.sh
```

On Codex, also enable subagent dispatch by adding the following to `~/.codex/config.toml`:

```toml
[features]
multi_agent = true
```

## Quickstart

Assuming you have already run `pipx install signal-export && sigexport ~/signal-chats` (or similar) and the exports are under `out/`:

```bash
# Discover available conversations
signal-brain list-sources
```

Then, from inside Claude Code or Codex, invoke the skill:

```
/signal-brain-build
```

(or describe what you want — "build the Amélie brain" — and the runtime will pick up the skill from its trigger description). The skill drives the full pipeline end-to-end: ingest → wiki synthesis → links → lint. It dispatches subagents for the LLM-shaped work and does not call any external API.

If you need to drive the pipeline step-by-step (for debugging, partial rebuilds, or custom orchestration), every stage is also available as a two-phase CLI command:

```bash
# Stage with LLM work — two-phase (--plan emits a todo file; agent fills it; --finalize consumes the done file)
signal-brain ingest --plan        --source Amélie
signal-brain ingest --finalize    --source Amélie
signal-brain build-wiki --plan    --source Amélie
signal-brain build-wiki --finalize --source Amélie
signal-brain link --stage 2 --plan    --source Amélie
signal-brain link --stage 2 --finalize --source Amélie

# Deterministic stages — no agent involvement
signal-brain build-index --source Amélie
signal-brain link --stage 1 --source Amélie
signal-brain lint        --source Amélie
signal-brain evaluate-bursts --plan --source Amélie --sample-size 20
```

If `out/` contains exactly one source directory, `--source` may be omitted.

## Layout

```
signal-convo/
  scripts/signal_brain/    # Python package — deterministic backbone + plan/finalize CLI
  scripts/tests/           # pytest suite (all offline; no API key)
  scripts/install-skills.sh # symlinks skills/ into ~/.claude/skills and ~/.codex/skills
  skills/
    signal-brain-build/    # orchestrator skill (works on Claude Code and Codex)
      SKILL.md
  docs/superpowers/        # design specs + implementation plans
  out/<source>/            # raw sigexport input (untouched)
  brain/                        # gitignored except for two files
    AGENTS.md                   # canonical agent guide for reading any source (committed)
    CLAUDE.md                   # mirror of AGENTS.md
    <source>/                   # per-source artifact (gitignored, regenerated locally)
      index.md
      log.md
      lint-report.md
      data/                     # machine layer (regeneratable; also holds todo/done worklists)
      people/ concepts/ positions/ arcs/ cross/
  config.toml              # tunable knobs
  AGENTS.md                # this file's sibling — project-level dev notes
  CLAUDE.md
  README.md                # you are here
```

Nothing under `brain/<source>/` is committed to version control. Each developer (or agent) runs the pipeline against their own `out/` exports and regenerates the brain locally. `brain/AGENTS.md` and `brain/CLAUDE.md` are the exception — they are committed as the canonical agent reader's guide.

## Configuration

`config.toml` exposes the meaningful knobs:

```toml
[me]
sender_label = "Me"
slug = "thomas-martin"
name = "Thomas Martin"

[bursts]
threshold_minutes = 60

[arcs]
min_burst_count = 2
min_msg_count = 20

[tagging]
# Optional one-sentence context hint about this conversation.
# Empty = the tagger stays neutral. Example: "two French friends debating politics and economics".
description = ""

# Optional seed topic vocabulary. Empty = the LLM proposes freely.
# Add slugs like ["topic-a", "topic-b"] to bias tagging toward known themes.
seed_tags = []
```

The tagger is **neutral by default** — the default system prompt describes only "a Signal conversation between two people" with no further bias. The optional `description` and `seed_tags` keys in `[tagging]` let you prime the LLM toward known themes for a specific conversation.

## Tests

```bash
source .venv/bin/activate
pytest -q
```

All tests run offline; no API key needed.

## Documentation

- Original design spec: [`docs/superpowers/specs/2026-05-19-signal-convo-brain-design.md`](docs/superpowers/specs/2026-05-19-signal-convo-brain-design.md)
- No-API-key redesign spec: [`docs/superpowers/specs/2026-05-19-no-api-key-build-redesign.md`](docs/superpowers/specs/2026-05-19-no-api-key-build-redesign.md)
- Implementation plans under [`docs/superpowers/plans/`](docs/superpowers/plans/)
- Known deferred issues: [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md)
- Agent guide for reading any brain source: `brain/AGENTS.md`
- Orchestrator skill (used by Claude Code / Codex to build a brain): [`skills/signal-brain-build/SKILL.md`](skills/signal-brain-build/SKILL.md)

## License

Personal project. Not currently licensed for redistribution.

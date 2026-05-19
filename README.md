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

Requires Python 3.11 or newer and an Anthropic API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...
```

## Quickstart

Assuming you have already run `pipx install signal-export && sigexport ~/signal-chats` (or similar) and the exports are under `out/`:

```bash
# Discover available conversations
signal-brain list-sources

# Run the pipeline for one source
signal-brain ingest        --source SébastienBéal
signal-brain build-wiki    --source SébastienBéal
signal-brain build-index   --source SébastienBéal
signal-brain link          --source SébastienBéal --stage all
signal-brain lint          --source SébastienBéal

# Tune the burst threshold by sampling boundaries
signal-brain evaluate-bursts --source SébastienBéal --sample-size 20
```

If `out/` contains exactly one source directory, `--source` may be omitted.

## Layout

```
signal-convo/
  scripts/signal_brain/    # Python package
  scripts/tests/           # pytest suite (66 tests)
  docs/superpowers/        # design spec + implementation plan
  out/<source>/            # raw sigexport input (untouched)
  brain/                        # gitignored except for two files
    AGENTS.md                   # canonical agent guide for reading any source (committed)
    CLAUDE.md                   # mirror of AGENTS.md
    <source>/                   # per-source artifact (gitignored, regenerated locally)
      index.md
      log.md
      lint-report.md
      data/                     # machine layer (regeneratable)
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

[llm]
tagging_model = "claude-haiku-4-5-20251001"
synthesis_model = "claude-sonnet-4-6"

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

LLM-touching code is mocked; no API key needed for the test suite.

## Documentation

- Design spec: [`docs/superpowers/specs/2026-05-19-signal-convo-brain-design.md`](docs/superpowers/specs/2026-05-19-signal-convo-brain-design.md)
- Implementation plan: [`docs/superpowers/plans/2026-05-19-signal-convo-brain.md`](docs/superpowers/plans/2026-05-19-signal-convo-brain.md)
- Known deferred issues: [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md)
- Agent guide for reading any brain source: `brain/AGENTS.md`

## License

Personal project. Not currently licensed for redistribution.

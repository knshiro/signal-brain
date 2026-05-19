# Agent guide — Signal Conversation Brain (project root)

This file (mirrored as `CLAUDE.md`) tells an agent working **on this codebase** how to navigate, develop, test, and extend it. For instructions on consuming a single conversation's brain, see `brain/<source>/AGENTS.md` instead.

## What the project is

A Python tool that turns a Signal conversation export into a Karpathy-style wiki "brain". Each conversation becomes one self-contained folder of markdown pages with citations resolving back to exact messages. See `README.md` for the public-facing overview.

## Where things live

```
scripts/signal_brain/   # Python package
  msg_index.py          # stable message IDs
  bursts.py             # L1 time-gap clustering + content hashing
  manifest.py           # incremental-ingest state
  citations.py          # parse/resolve [Bnnnn#mN] citations
  llm.py                # Anthropic SDK wrapper with retry + JSON parse
  tagging.py            # L2a per-burst topic tagger (cache-aware)
  arcs.py               # L2b consecutive-topic arc detection
  ingest.py             # full pipeline: load -> diff -> L1 -> L2 -> manifest
  sources.py            # source-conversation discovery, slugify
  indexing.py           # build_index, bootstrap_brain_root, append_log
  linking.py            # link pass: Stage 1 deterministic + Stage 2 LLM lateral
  lint.py               # health checks
  evaluators.py         # one-shot burst-threshold evaluator
  cli.py                # signal-brain CLI (Click)
  wiki/
    schemas.py          # frontmatter + section validators
    people.py concepts.py positions.py arcs.py cross.py  # page generators
    build.py            # orchestrate which pages exist, summarize bursts, generate

scripts/tests/          # pytest suite, 66 tests
  conftest.py           # shared fixtures: mini_messages, tmp_data_dir, tmp_wiki_dir
  fixtures/mini_data.json  # 50-message slice for integration tests (synthetic senders: "Me"/"Friend", name "Alice Example")

docs/superpowers/specs/  # the design spec
docs/superpowers/plans/  # the 16-task implementation plan
out/<source>/            # raw sigexport input (immutable)
brain/                   # gitignored except AGENTS.md and CLAUDE.md at the root
  AGENTS.md              # canonical agent guide for reading any source (committed)
  CLAUDE.md              # mirror of AGENTS.md
  <source>/              # per-source artifact (gitignored, regenerated locally)
KNOWN_ISSUES.md          # carry-forward items from per-task reviews
config.toml              # tunable knobs (bursts, arcs, llm models, me identity, tagging priming)
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...   # required for ingest / build-wiki / link --stage 2 / evaluate-bursts
```

## Run tests before and after every change

```bash
source .venv/bin/activate
pytest -q       # full suite (LLM mocked; no API key needed)
```

Tests should always be green. If you change a public function signature, update its tests in the same commit.

## Standing conventions

These are non-negotiable. Past review cycles enforced them; future code must follow.

- **UTF-8 explicit on every file I/O.** All `Path.read_text(...)` and `Path.write_text(...)` calls include `encoding="utf-8"`. The codebase has UTF-8 sender labels (`SébastienBéal`) and French source content; default encoding is unreliable across platforms.
- **Python 3.11+ type hints.** Use built-in generics (`list[dict]`, `dict[str, int]`, `str | None`) — no `typing.List`/`Optional`.
- **Slug rules.** Lowercase ASCII, kebab-case, no diacritics. `slugify("BjörkGuðmundsdóttir") == "bjorkgudmundsdottir"`. See `scripts/signal_brain/sources.py`.
- **Citation format.** `[Bnnnn#mN]` where `Bnnnn` is a 4-digit zero-padded burst id and `mN` is the 1-indexed position of the message inside that burst's `msg_ids`. Always cite; lint catches unresolved citations.
- **Wiki content is English.** Quoted source material is preserved verbatim in French inside citations.
- **`## Related` section in wiki pages is auto-maintained.** Only the link pass writes it; never hand-edit.
- **Content-neutral defaults.** The topic tagger and slug examples carry no conversation-specific terms. The default system prompt describes only "a Signal conversation between two people". Per-thread priming lives in `config.toml` under `[tagging]` (`description` and `seed_tags`).

## CLI surface

```
signal-brain --help
  list-sources
  ingest         --source <name>
  build-wiki     --source <name>
  build-index    --source <name>
  link           --source <name> --stage 1|2|all
  lint           --source <name>
  evaluate-bursts --source <name> --sample-size <n>
```

`--source` is optional when exactly one conversation lives under `out/`. The pipeline order matters: `ingest` must precede `build-wiki`; `build-wiki` should precede `build-index`, `link`, and `lint`.

## TDD workflow

1. Write a failing test first.
2. Run it: `pytest scripts/tests/<your_test>.py -v` — confirm the right failure (e.g., `ModuleNotFoundError`).
3. Implement the minimal code to make it pass.
4. Run tests again — confirm green.
5. Commit. Use focused commits (`feat:`, `fix:`, `chore:`, `refactor:`).

## Where to look first

- **Adding a feature**: read the spec section it relates to, then the corresponding plan task. The plan code IS the reference implementation.
- **Fixing a bug**: check `KNOWN_ISSUES.md` first — it may already be tracked. If not, add it.
- **Understanding the data flow**: `scripts/signal_brain/ingest.py::run_ingest_data_layer` is the end-to-end backbone.
- **Understanding wiki generation**: `scripts/signal_brain/wiki/build.py::plan_pages` decides what pages to make; `build.py::build_wiki` runs the generators.
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
- Never re-introduce conversation-specific terms into production code or the default config. The codebase is intentionally generic; per-thread priming lives exclusively in `config.toml [tagging]`.

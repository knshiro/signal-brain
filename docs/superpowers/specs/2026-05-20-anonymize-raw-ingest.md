# Spec — Anonymize raw ingest

**Status:** Approved 2026-05-20. Plan: `docs/superpowers/plans/2026-05-20-anonymize-raw-ingest.md`.

## Problem

Some Signal conversations contain the operator's real name in message bodies — the other party may address them directly ("Ugo, regarde ça…"). Today only the *sender label* is renamed through `config.toml [me]` (`Me` → "Thomas Martin"); message *content* flows through unchanged.

So `grep -ri "ugo" brain/<src>/` returns hits, defeating the point of the pseudonym for any agent that searches raw data.

## Goal

After this PR, when a user configures their real-name aliases in `config.toml [me]`, those aliases are scrubbed from message bodies during ingest, before anything is written under `brain/<src>/data/`. The pseudonym remains greppable; the real name does not.

## Non-goals

- **The source export under `out/<src>/data.json` is not modified.** It is the immutable input. The scrub runs as data flows into `brain/<src>/data/`.
- **Other parties' real names are out of scope.** This PR is exclusively about the operator's identity. A future PR could generalise.
- **Existing brains are not retroactively re-scrubbed.** Users with already-built brains re-run `signal-brain ingest --plan` (and the rest of the pipeline) to pick up the scrub. Burst content hashes will change once across the cut-over; that's expected.

## Design

### Configuration

Extend the `[me]` section in `config.toml` with an optional `real_names` list:

```toml
[me]
sender_label = "Me"
slug = "thomas-martin"
name = "Thomas Martin"
real_names = ["Ugo", "Ugo Bataillard"]   # NEW — optional, defaults to []
```

Empty list = no scrubbing (current behaviour). Patterns are plain strings; not regex.

### Scrubber semantics

- **Word-boundary anchored.** `\bUgo\b` so "Hugo" is never replaced.
- **Case-insensitive match.** `ugo`, `Ugo`, `UGO` all match.
- **Case-preserved replacement.**
  - `ugo` → `thomas` (lowercase preserved)
  - `Ugo` → `Thomas` (Title-case preserved)
  - `UGO` → `THOMAS` (all-caps preserved)
- **Longest-match-first.** `"Ugo Bataillard"` matches before `"Ugo"`, so multi-token patterns are not destroyed by a greedier single-token rule.
- **Replacement target derived from `[me].name`:**
  - Patterns with 2+ whitespace-delimited tokens → replaced by full `name` ("Thomas Martin").
  - Patterns with 1 token → replaced by the first token of `name` ("Thomas").

### Where the scrub is applied

A single point: `msg_index.build_msg_index`. The scrubbed text lands in the `body` and `quote` fields of `msg_index.jsonl`. From there it propagates naturally:

- `bursts.burst_content_hash` hashes already-scrubbed bodies → stable across runs after the cut-over.
- `tagging._render_burst_for_tagging` reads already-scrubbed bodies → todo/done prompts never embed the real name.
- Wiki synthesis reads chunks (which derive from bursts which derive from msg_index) → wiki page bodies never embed the real name.
- Lateral linking reads wiki pages → same.

Applying the scrub once at the top of the pipeline is the only place that matters; everything downstream inherits it.

## Acceptance criteria

1. **Real name absent from `brain/<src>/`.** After a fresh ingest on the SébastienBéal export with `real_names = ["Ugo", "Ugo Bataillard"]` configured, `grep -ri "ugo" brain/SébastienBéal/` returns no matches (case-insensitive). The other party uses the real name in at least a few messages today, so this is a real signal.
2. **Pseudonym still greppable.** `grep -ri "thomas" brain/SébastienBéal/` continues to return matches (via the sender label, slug, and any new replacements).
3. **Word-boundary correctness.** A burst containing the word "Hugo" (or similar substring) is not corrupted into "Hthomas".
4. **Defaults are inert.** With `real_names = []` (or absent), `build_msg_index` output is byte-identical to the current behaviour; all existing tests pass without modification.
5. **Hash stability.** Two consecutive runs with the same scrubber config produce identical burst content hashes (no spurious cache misses after the initial cut-over).

## Sequencing relative to taxonomy-first

Ships **before** taxonomy-first. Reason: any canonical taxonomy slugs derived from scrubbed text are stable; running it after would mean re-running ingest, which invalidates the taxonomy cache and forces a regeneration.

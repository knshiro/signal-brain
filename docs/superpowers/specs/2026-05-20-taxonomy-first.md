# Spec — Taxonomy-first ingest

**Status:** Approved 2026-05-20. Plan: `docs/superpowers/plans/2026-05-20-taxonomy-first.md`.

## Problem

Per-burst tagging without a shared vocabulary produces N unique slugs from N bursts. Each burst's tagger sees only its own messages and coins fresh slugs ("billionaires", "wealth-concentration", "wealth-accumulation", "rich-people", "capital", "ultra-rich"…) for what is semantically the same theme. The downstream concept/position/arc layer requires `min_concept_bursts` bursts to share a slug before a concept page fires; on small conversations (~150 bursts), no slug ever clears that bar, and the wiki ends up empty of the very concept and position pages the design promised.

The PR #1 smoke test confirmed this empirically on the Amélie export: zero `concepts/` pages, zero `positions/` pages, despite the conversation clearly containing recurring themes.

## Goal

Add a new stage upstream of per-burst tagging that produces a *canonical vocabulary* — a small, conversation-specific list of slugs — and then forces per-burst tagging to draw from that vocabulary. This matches how a human curator would do it: skim the whole conversation, identify the themes, then tag burst-by-burst with the slug list in hand.

After this PR, on the Amélie export:
- ≥1 `concepts/` page on a wealth-concentration-themed slug.
- ≥1 `positions/thomas-martin--*.md` page.
- The original failing query ("Thomas' position on accumulation of capital…") cites a position page, not just bursts.

## Non-goals

- **No lowering of `min_concept_bursts`.** That's a knob the spec already exposes; lowering it would have papered over the problem. Canonicalisation does the real work. Tuning the knob is a separate conversation, post-landing.
- **No automatic taxonomy editing UI.** The taxonomy is regenerated from the full conversation each time the source diff changes; manual override is out of scope.
- **No multi-source taxonomies.** Each conversation has its own taxonomy. Cross-conversation canonical vocabulary is a future concern.

## Design

### New stage in the worklist contract

Introduce a new stage `taxonomy` upstream of `tagging`. It uses the same plan/finalize contract as every other LLM-shaped stage (one todo row in → one done row out, idempotent by `job_id`).

**Cardinality:** one todo per ingest run. The taxonomy is a global property of the source, not per-burst. Input is the full conversation flattened to plain text; output is two slug lists plus a freeform `notes` string.

```python
TAXONOMY_RESPONSE_SCHEMA = {
    "required": ["taxonomy", "concepts", "notes"],
    "types": {"taxonomy": "list", "concepts": "list", "notes": "str"},
}
```

`taxonomy` is the full controlled vocabulary used for per-burst tagging. `concepts` is the subset of `taxonomy` slugs the model judges substantial enough to warrant their own wiki page — themes the two people *develop arguments about*, not incidental logistics or banter. `concepts ⊆ taxonomy`.

**Topic granularity (better topic creation).** The taxonomy system prompt instructs the model to produce *concept-grade* topics: each slug must be broad enough to recur across the conversation, and facets of one theme must be merged into a single umbrella slug rather than fragmented into siblings (e.g. wealth concentration, billionaires, and wealth taxation are facets of ONE topic, not three). Target ~10–18 topics; past ~20 the model is fragmenting.

### Cache key: source content hash

The taxonomy is cached at `brain/<src>/data/taxonomy.json`:

```json
{
  "source_hash": "sha1:abc123…",
  "taxonomy": ["wealth-and-inequality", "role-of-the-state", "comparative-economic-models", ...],
  "concepts": ["wealth-and-inequality", "role-of-the-state", ...],
  "notes": "Themes recur across the timeline; wealth-and-inequality is the spine of the debate…"
}
```

`load_taxonomy_cache` returns the full validated dict (or `None`) and is used by `run_ingest_plan` to read `taxonomy` for the tagging vocabulary — the source-hash check belongs to the ingest stage, where taxonomy/source consistency is established. `build_wiki_plan` reads `concepts` from `taxonomy.json` directly (helper `_load_concepts`): it consumes `data_dir` as a single consistent ingest snapshot — taxonomy.json, chunks.jsonl, and bursts.jsonl are all produced by one ingest cycle — so it does not re-validate the hash, consistent with how it already reads `chunks.jsonl` unchecked.

Cache hit when `source_hash` matches the SHA1 of the current msg_index. On hit, no taxonomy todo is emitted; the cached taxonomy is fed directly into the tagging stage. Cache miss = a new ingest run with non-trivially changed source → regenerate.

### Per-burst tagging changes

When a taxonomy is present, two things change in the tagging prompts:

1. **System prompt.** Add a hard constraint: "You must select all `topics` from the provided controlled vocabulary. Only set `out_of_taxonomy: true` (and propose a new slug in `topics`) when no vocabulary term genuinely fits."
2. **User prompt.** Inject the taxonomy as "Required vocabulary" instead of the soft "Seed tags" framing. The list is the same shape; the framing is harder.

Add a new field to `TAGGING_RESPONSE_SCHEMA`:

```python
TAGGING_RESPONSE_SCHEMA = {
    "required": ["topics", "primary", "summary", "out_of_taxonomy"],
    "types": {"topics": "list", "primary": "str", "summary": "str",
              "out_of_taxonomy": "bool"},
}
```

When `out_of_taxonomy=true`, the chunk is flagged for the lint pass. A high rate of out-of-taxonomy bursts signals the taxonomy is too narrow and merits regeneration (e.g., via deleting `taxonomy.json` and re-running ingest).

When no taxonomy is configured (e.g., first run, or user explicitly disabled it), the tagger falls back to today's neutral behaviour — `out_of_taxonomy` defaults to false and seed_tags are soft hints, exactly as today.

### Hash cascading

The taxonomy is folded into the burst content hash, so any taxonomy change invalidates all chunks and forces retagging:

```python
def burst_content_hash(burst, all_messages, taxonomy_hash: str = "") -> str:
    # existing logic, plus h.update(taxonomy_hash.encode()) at the end
```

This is the correct behaviour: when the controlled vocabulary changes, the tagger's output for the same burst content can legitimately differ, so the cache must invalidate.

### Self-progressing `ingest --plan`

`run_ingest_plan` becomes staged. On any single call:

1. Build msg_index and bursts (deterministic, as today).
2. Compute the source content hash.
3. Load taxonomy cache. If `source_hash` matches → taxonomy is fresh, skip step 4.
4. Else: emit one taxonomy todo, set `stats["taxonomy_pending"] = True`, do NOT emit tagging todos, return early.
5. With a fresh taxonomy in hand, emit tagging todos with the taxonomy as required vocabulary.

The orchestrator skill loops:

```
while True:
    run ingest --plan
    if stats.taxonomy_pending: fan out taxonomy stage; continue
    if stats.tagging_todos > 0: fan out tagging stage
    break
run ingest --finalize
```

Two-step convergence: first iteration emits taxonomy todo, second iteration sees taxonomy.done and emits tagging todos. No CLI surface change; only `run_ingest_plan` internals change.

### Finalize side

`run_ingest_finalize` reads taxonomy.done (if present, i.e., if a fresh one was generated in this cycle) and writes `taxonomy.json` to disk. It also feeds `out_of_taxonomy` through into `chunks.jsonl` so the lint pass can read it.

### Lint check

New lint check: `out_of_taxonomy_rate`. Reports the fraction of chunks where `out_of_taxonomy=true`. Above ~25%, surface a warning that the taxonomy is under-fitted to the conversation and suggest re-running ingest after deleting `taxonomy.json`.

### Concept and position page selection

`min_concept_bursts` is removed. Page selection is no longer a burst-count threshold — it is the model's judgment, captured in the `concepts` list.

`wiki/build.py::plan_pages`:

- Counts every topic on a burst (the full `topics` list), not just `primary`. A burst that substantively covers a topic contributes to that topic even when it is not the single dominant one.
- A **concept page** `concepts/<slug>.md` is planned for each slug in the taxonomy's `concepts` list that is backed by at least one chunk (the ≥1-burst floor guarantees a citable source).
- A **position page** `positions/<holder>--<slug>.md` is planned for each (holder, concept-slug) pair backed by at least one burst where that holder participated and the slug is in the burst's topics.

`build_wiki_plan` loads `taxonomy.json` to obtain the `concepts` list and passes it to `plan_pages`; the `min_concept_bursts` parameter is dropped from both. When no `taxonomy.json` exists (taxonomy stage never ran), `concepts` is empty and no concept or position pages are planned — a graceful degradation, not an error.

## Acceptance criteria

On a fresh end-to-end run on the Amélie export with the orchestrator skill:

1. **`brain/Amélie/data/taxonomy.json` exists** and contains a non-empty `taxonomy` list (expected size ~10–18) and a non-empty `concepts` subset.
2. **All non-out-of-taxonomy `chunks.jsonl` rows have `topics ⊆ taxonomy`.** Spot-check by inspecting a few rows.
3. **At least one concept page exists** on a wealth-themed slug under `brain/Amélie/concepts/` — e.g. `concepts/wealth-and-inequality.md`. The taxonomy must produce a single un-fragmented wealth topic and mark it a concept.
4. **At least one `positions/thomas-martin--*.md` page exists.**
5. **The query that motivated this work** — "What is Thomas' position on accumulation of capital and inequality?" — now resolves to a position page, not just a list of bursts.
6. **Idempotence.** Re-running `signal-brain ingest --plan` immediately after a successful finalize is a no-op (taxonomy cache hit, no new tagging todos).

## Sequencing relative to anonymize-raw-ingest

Ships **after** `anonymize-raw-ingest`. Reason: taxonomy slugs derived from scrubbed text are stable; running first would mean re-running ingest after the scrubber lands, invalidating the taxonomy cache for no reason.

## Open questions deferred to follow-ups

- **Taxonomy prompt tuning per conversation.** Today's `[tagging]` section has `description` and `seed_tags` — these flow into both the taxonomy and tagging prompts unchanged. If we find taxonomies are systematically too broad or too narrow, we'll introduce `[taxonomy]` knobs separately.
- **Multi-language taxonomies.** Current Amélie export is mostly French; the tagger outputs English slugs. We assume the taxonomy stage handles that fine. Verify in the smoke test.
- **Taxonomy size cap.** Don't enforce one initially. Add only if we see runaway lists.

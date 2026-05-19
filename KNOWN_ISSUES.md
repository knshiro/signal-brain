# Known issues — deferred from per-task reviews

These items surfaced during code-quality reviews and the final whole-implementation audit. None blocks the **first build** (ingest → build-wiki → build-index → link → lint). All matter once the re-export loop becomes a regular workflow.

## Spec deviations

1. **L3 dirty-propagation absent.** Spec §9 step 6 says re-export should flag wiki pages as `needs-update` in `log.md` when their topic overlaps a dirty burst. Current `run_ingest_data_layer` does not flag any wiki pages; the operator must manually re-run `build-wiki` after `ingest`. Re-exports otherwise silently miss L3 updates.
2. **Tail-only burst optimization absent.** Spec §9 step 2 says only the last existing burst plus new messages should be re-bursted on re-export. Current code re-bursts everything every run (cheap at 2.3k messages, expensive at 100k+).
3. **Linking spec drift.** Spec §10 Stage 1 says arc ↔ position should link via **burst overlap**. Code links via shared `primary_topic` ↔ `concept`. Functionally similar but not what the spec specifies.

## Unimplemented features

4. **Three lint checks are stubs.** `Stale claims`, `Tag synonyms`, and `Missing concept pages` rows always emit `(none)`. The corresponding `findings[...]` lists are scaffolded but no logic populates them. Spec §11 specifies the behavior for each.
5. **Three config knobs unread.** `cross_pages.min_occurrences`, `lint.stale_claim_ingestion_count`, and `lint.position_evolution_threshold` exist in `config.toml` but nothing reads them. They become live when the corresponding lint checks land.

## Quality / robustness

6. **`build_wiki` hardcodes `min_concept_bursts=5`.** `config.toml` has no matching key. Should add `[wiki] min_concept_bursts = 5` and wire it through `cli.py`'s `build-wiki` command.
7. **`counterpart_summary` is a placeholder.** In `scripts/signal_brain/wiki/build.py` the position-page generator passes the holder's own burst summary as the counterpart's. Comment acknowledges "adequate first pass". Real counterpart summary needs to filter the same arc's bursts by sender.
8. **`evaluate_bursts` indexes `msgs[mid]` without `.get()` guard.** `KeyError` on a missing message ID. Low risk (`bursts.jsonl` and `msg_index.jsonl` are produced together), but defensive code would not hurt.
9. **`Manifest` schema-version mismatch silently starts fresh.** Currently behaves as "fresh init" without warning. Should log a one-line notice.
10. **`complete_json` regex fragile on truncated output.** If the model returns text with an opening ```` ``` ```` fence and no closing fence (e.g., hit `max_tokens`), the regex matches an empty string and `json.loads` fails with a confusing error. Should explicitly assert the closing fence or fall back to raw parse.
11. **`citations._load` double-reads each file.** Once for `.strip()` check, once for `.splitlines()`. Benign (cached) but inelegant.
12. **`detect_bursts` doesn't tolerate mixed timezone-aware/naive timestamps.** Signal exports today are naive, so this is fine — but a future change to sigexport could break it.
13. **`burst_content_hash` raises `KeyError`** if a burst references a `msg_id` not in `all_messages`. Caller is expected to pass the same list, but a defensive guard would surface the bug sooner.
14. **Wikilink lint uses full `sub/name` keys**, but page bodies commonly write `[[name]]` (bare). Bare-name links are silently treated as missing, under-counting inbound for orphan detection.
15. **Lint output is insertion-order, not sorted.** Report ordering varies across runs depending on filesystem traversal.
16. **Bare `except Exception` in `LLMClient` retry loop.** Catches everything including programmer errors. Should narrow to `anthropic.APIError` family.
17. **`Manifest.load_or_init` silently uses on-disk threshold** even if caller passes a different one. Document the intent or warn on mismatch.

## Carry-forward but cosmetic

18. **`build-wiki` and `lint` commands lacked docstrings** — fixed during Task 15 review.
19. **`anthropic>=0.40.0`** lower bound was too low for `claude-haiku-4-5-20251001` — bumped to `0.49.0` during Task 1 review.
20. **`.gitignore` missed cache dirs** — added `.mypy_cache/`, `.ruff_cache/`, `*.egg` during Task 1 review.

## Recommendation

Before regular re-export use:
- Fix items **1** (dirty-flag propagation) and **4** (lint checks) — these are the highest-impact missing features.
- Items **3** (linking spec drift) and **7** (counterpart summary) affect output quality once you have enough conversation data to make distinctions.

For first build, ship as-is.

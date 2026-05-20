# Anonymize Raw Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrub the operator's real-name aliases from message bodies during ingest so they never appear under `brain/<src>/`, while keeping the pseudonym fully greppable.

**Architecture:** One new module (`anonymize.py`) exposing `compile_scrubber(real_names, replacement_full) -> Callable[[str], str]`. The scrubber is built once per ingest from `config.toml [me].real_names` + `[me].name`, then applied inside `msg_index.build_msg_index` to the `body` and `quote` fields. Everything downstream inherits the scrubbed text — no other call site needs to know the scrubber exists.

**Tech Stack:** Python 3.11+, `re` standard library, existing pytest suite. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-20-anonymize-raw-ingest.md`
**Branch:** `feat/anonymize-ingest`

---

## File Structure

- **Create:** `scripts/signal_brain/anonymize.py` — scrubber compilation + case-preservation helpers.
- **Create:** `scripts/tests/test_anonymize.py` — unit tests for scrubber semantics.
- **Modify:** `scripts/signal_brain/msg_index.py` — add `scrub` parameter to `build_msg_index`, apply to `body` and `quote`.
- **Modify:** `scripts/tests/test_msg_index.py` — add coverage for the `scrub` parameter (default-off and on).
- **Modify:** `scripts/signal_brain/ingest.py` — wire `real_names`/`name` from config into a scrubber, pass to `build_msg_index`.
- **Modify:** `scripts/signal_brain/cli.py` — pass `[me]` config through to `run_ingest_plan`.
- **Modify:** `scripts/tests/test_ingest.py` (or add minimal test) — end-to-end scrub through `run_ingest_plan`.
- **Modify:** `config.toml` — document `real_names` with an empty default.
- **Modify:** `CLAUDE.md` and `AGENTS.md` — one-paragraph note on the convention.

---

## Task 1: Scrubber module + unit tests

**Files:**
- Create: `scripts/signal_brain/anonymize.py`
- Test: `scripts/tests/test_anonymize.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_anonymize.py`:

```python
"""Tests for the operator-identity scrubber."""
from signal_brain.anonymize import compile_scrubber


def test_empty_real_names_returns_identity():
    scrub = compile_scrubber([], "Thomas Martin")
    text = "Ugo wrote this. Hugo also wrote that. UGO is loud."
    assert scrub(text) == text


def test_single_token_replaced_with_first_word_of_name():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("Hey Ugo, how's it going?") == "Hey Thomas, how's it going?"


def test_multi_token_replaced_with_full_name():
    scrub = compile_scrubber(["Ugo Bataillard"], "Thomas Martin")
    assert scrub("Signed, Ugo Bataillard.") == "Signed, Thomas Martin."


def test_longest_match_first():
    """Multi-token patterns must win over single-token ones at the same position."""
    scrub = compile_scrubber(["Ugo", "Ugo Bataillard"], "Thomas Martin")
    # If "Ugo" matched first, we'd get "Thomas Bataillard" — wrong.
    assert scrub("From Ugo Bataillard today") == "From Thomas Martin today"


def test_case_preservation_lowercase():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("ugo répond") == "thomas répond"


def test_case_preservation_titlecase():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("Ugo répond") == "Thomas répond"


def test_case_preservation_uppercase():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("UGO RÉPOND") == "THOMAS RÉPOND"


def test_word_boundary_does_not_match_substring():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    # "Hugo" must NOT become "Hthomas".
    assert scrub("Hugo Pratt is unrelated.") == "Hugo Pratt is unrelated."


def test_word_boundary_with_punctuation():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("salut Ugo!") == "salut Thomas!"
    assert scrub("(Ugo)") == "(Thomas)"
    assert scrub("Ugo, viens") == "Thomas, viens"


def test_multiple_occurrences_in_one_string():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("Ugo et Ugo") == "Thomas et Thomas"


def test_french_diacritics_in_surroundings_do_not_break_boundary():
    """A French word right next to the match must not extend the match."""
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("très Ugo très") == "très Thomas très"


def test_empty_input_is_safe():
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    assert scrub("") == ""
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest scripts/tests/test_anonymize.py -v`
Expected: ALL FAIL with `ModuleNotFoundError: No module named 'signal_brain.anonymize'`.

- [ ] **Step 3: Implement the scrubber module**

Create `scripts/signal_brain/anonymize.py`:

```python
"""Operator-identity scrubber.

Builds a `scrub(text) -> text` function from a list of real-name patterns and a
replacement pseudonym. Used at ingest time so the operator's real name never
lands under `brain/<src>/`.

Semantics: word-boundary match, case-insensitive, case-preserved replacement,
longest-match-first. See `docs/superpowers/specs/2026-05-20-anonymize-raw-ingest.md`.
"""
from __future__ import annotations

import re
from typing import Callable


def _preserve_case(replacement: str, matched: str) -> str:
    """Apply the casing of `matched` to `replacement`.

    Rules (in order):
    - matched is all uppercase (and has letters) → uppercase replacement.
    - matched's first character is uppercase → titlecase replacement (first char
      upper, rest lowercase).
    - otherwise (all lowercase or no leading letter) → lowercase replacement.
    """
    if matched.isupper() and any(c.isalpha() for c in matched):
        return replacement.upper()
    if matched[:1].isupper():
        return replacement[:1].upper() + replacement[1:].lower()
    return replacement.lower()


def compile_scrubber(
    real_names: list[str],
    replacement_full: str,
) -> Callable[[str], str]:
    """Compile a scrubber that replaces real-name patterns with a pseudonym.

    - `real_names`: list of plain-string patterns. Empty list → identity scrubber.
    - `replacement_full`: the full pseudonym (e.g. "Thomas Martin"). Multi-token
      patterns map to the full pseudonym; single-token patterns map to the first
      whitespace-delimited word of the pseudonym (e.g. "Thomas").

    Matches are word-boundary anchored, case-insensitive, and longest-pattern-first.
    The casing of the matched text is preserved on the replacement.
    """
    if not real_names:
        return lambda text: text

    first_word = replacement_full.split()[0] if replacement_full.split() else replacement_full

    sorted_patterns = sorted(real_names, key=lambda p: -len(p.split()))

    compiled: list[tuple[re.Pattern[str], str]] = []
    for pattern in sorted_patterns:
        if not pattern.strip():
            continue
        regex = re.compile(rf"\b{re.escape(pattern)}\b", re.IGNORECASE | re.UNICODE)
        replacement = replacement_full if len(pattern.split()) > 1 else first_word
        compiled.append((regex, replacement))

    def scrub(text: str) -> str:
        if not text:
            return text
        for regex, replacement in compiled:
            text = regex.sub(
                lambda m, r=replacement: _preserve_case(r, m.group(0)),
                text,
            )
        return text

    return scrub
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest scripts/tests/test_anonymize.py -v`
Expected: 11 passed.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/signal_brain/anonymize.py scripts/tests/test_anonymize.py
git commit -m "feat(anonymize): compile_scrubber for operator-identity replacement"
```

---

## Task 2: Wire scrubber into `build_msg_index`

**Files:**
- Modify: `scripts/signal_brain/msg_index.py` (function `build_msg_index`)
- Test: `scripts/tests/test_msg_index.py` (extend with scrubber coverage)

- [ ] **Step 1: Write the failing tests**

Add to `scripts/tests/test_msg_index.py`:

```python
from signal_brain.anonymize import compile_scrubber


def test_build_msg_index_scrubs_body_when_scrubber_provided(tmp_data_dir):
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "Hey Ugo, look at this", "quote": "", "reactions": [], "attachments": []},
    ]
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out, scrub=scrub)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["body"] == "Hey Thomas, look at this"
    assert "Ugo" not in row["body"]


def test_build_msg_index_scrubs_quote_field(tmp_data_dir):
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "réponse", "quote": "Ugo a écrit ça", "reactions": [], "attachments": []},
    ]
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out, scrub=scrub)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["quote"] == "Thomas a écrit ça"


def test_build_msg_index_scrubber_default_is_identity(tmp_data_dir):
    """Without a scrubber, body is passed through unchanged (back-compat)."""
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "Hey Ugo", "quote": "", "reactions": [], "attachments": []},
    ]
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out)  # no scrub kwarg
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["body"] == "Hey Ugo"


def test_build_msg_index_char_count_uses_scrubbed_length(tmp_data_dir):
    """char_count must reflect the post-scrub body, not the original."""
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "Ugo", "quote": "", "reactions": [], "attachments": []},
    ]
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out, scrub=scrub)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["char_count"] == len("Thomas")
```

- [ ] **Step 2: Run new tests, confirm they fail**

Run: `pytest scripts/tests/test_msg_index.py -v`
Expected: the four new tests fail (`TypeError: build_msg_index() got an unexpected keyword argument 'scrub'` for the first three; the fourth passes today but won't after Step 3 either — re-check after impl).

- [ ] **Step 3: Modify `build_msg_index`**

Edit `scripts/signal_brain/msg_index.py`. Replace the existing `build_msg_index` with:

```python
def build_msg_index(
    messages: Iterable[dict],
    out_path: Path,
    *,
    scrub: Callable[[str], str] | None = None,
) -> int:
    """Write deduplicated msg_index.jsonl. Returns row count.

    If `scrub` is provided, it's applied to the `body` and `quote` fields before
    they're written. The resulting `char_count` reflects the post-scrub body.
    """
    apply = scrub or (lambda s: s)
    seen: set[str] = set()
    rows = []
    for m in messages:
        mid = msg_id(m)
        if mid in seen:
            continue
        seen.add(mid)
        body = apply(m.get("body", ""))
        quote = apply(m.get("quote", ""))
        rows.append({
            "msg_id": mid,
            "date": m["date"],
            "sender": m["sender"],
            "body": body,
            "quote": quote,
            "reactions": m.get("reactions", []),
            "attachments": m.get("attachments", []),
            "char_count": len(body),
        })
    Path(out_path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return len(rows)
```

Add the import at the top of the file:

```python
from typing import Callable, Iterable
```

(Existing import is `from typing import Iterable` — extend it.)

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest scripts/tests/test_msg_index.py -v`
Expected: all tests pass (existing 3 + new 4).

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests pass. No regressions in tagging, bursts, ingest, etc.

- [ ] **Step 6: Commit**

```bash
git add scripts/signal_brain/msg_index.py scripts/tests/test_msg_index.py
git commit -m "feat(msg_index): optional scrub callable applied to body and quote"
```

---

## Task 3: Wire scrubber through `run_ingest_plan` and CLI

**Files:**
- Modify: `scripts/signal_brain/ingest.py` (`run_ingest_plan` signature + call site)
- Modify: `scripts/signal_brain/cli.py` (pass `[me]` config through)
- Test: `scripts/tests/test_ingest.py` (end-to-end scrub assertion)

- [ ] **Step 1: Write the failing end-to-end test**

Add to `scripts/tests/test_ingest.py` (top of file if not already imported, otherwise just the test):

```python
def test_run_ingest_plan_scrubs_real_names_when_configured(tmp_path):
    """End-to-end: configuring real_names removes the literal from msg_index.jsonl."""
    source = tmp_path / "src.jsonl"
    source.write_text(json.dumps({
        "date": "2026-05-05T13:18:00.000000",
        "sender": "Friend",
        "body": "Salut Ugo, ça va ?",
        "quote": "",
        "reactions": [],
        "attachments": [],
    }) + "\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    run_ingest_plan(
        source_path=source,
        data_dir=data_dir,
        burst_threshold_min=60,
        me_real_names=["Ugo"],
        me_name="Thomas Martin",
    )
    body = (data_dir / "msg_index.jsonl").read_text(encoding="utf-8")
    assert "Ugo" not in body
    assert "Thomas" in body
```

(If `test_ingest.py` doesn't import `run_ingest_plan` and `json`, add them.)

- [ ] **Step 2: Run, confirm it fails**

Run: `pytest scripts/tests/test_ingest.py::test_run_ingest_plan_scrubs_real_names_when_configured -v`
Expected: FAIL — `run_ingest_plan` doesn't accept `me_real_names` / `me_name` yet.

- [ ] **Step 3: Extend `run_ingest_plan`**

Edit `scripts/signal_brain/ingest.py`. Add the import at top:

```python
from signal_brain.anonymize import compile_scrubber
```

Update `run_ingest_plan`'s signature and the `build_msg_index` call:

```python
def run_ingest_plan(*, source_path: Path, data_dir: Path,
                    burst_threshold_min: int,
                    tagging_description: str = "",
                    tagging_seed_tags: list[str] | None = None,
                    me_real_names: list[str] | None = None,
                    me_name: str = "") -> dict:
    """Build msg_index + bursts, emit tagging todos. No LLM, no arcs yet.

    Idempotent: re-emitting todos for the same burst content is a no-op.

    `me_real_names` + `me_name` configure the operator-identity scrubber. When
    `me_real_names` is non-empty, occurrences of those patterns in message
    bodies and quotes are replaced with `me_name` (or its first token, for
    single-token patterns) before anything is written under `data_dir`.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    p = _data_paths(data_dir)

    scrub = compile_scrubber(me_real_names or [], me_name)

    source = _load_raw(source_path)
    diff = diff_messages(source, p["msg_index"])
    build_msg_index(source, p["msg_index"], scrub=scrub)
    msgs = load_msg_index(p["msg_index"])
    # ... rest unchanged
```

(Keep the rest of the function body identical.)

- [ ] **Step 4: Wire `[me]` config in the CLI**

Edit `scripts/signal_brain/cli.py`. In the `ingest` command, change the `--plan` branch to pass the `[me]` config:

```python
    if phase == "plan":
        me_cfg = cfg.get("me", {})
        stats = run_ingest_plan(
            source_path=source_path,
            data_dir=data_dir,
            burst_threshold_min=cfg["bursts"]["threshold_minutes"],
            tagging_description=tagging_cfg.get("description", ""),
            tagging_seed_tags=tagging_cfg.get("seed_tags") or None,
            me_real_names=me_cfg.get("real_names") or None,
            me_name=me_cfg.get("name", ""),
        )
```

- [ ] **Step 5: Run the new test and full suite**

Run: `pytest scripts/tests/test_ingest.py -v`
Expected: the new test passes.

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/signal_brain/ingest.py scripts/signal_brain/cli.py scripts/tests/test_ingest.py
git commit -m "feat(ingest): apply operator-identity scrubber from [me].real_names"
```

---

## Task 4: Config + docs

**Files:**
- Modify: `config.toml`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `brain/AGENTS.md`, `brain/CLAUDE.md` (the agent-consumption guides) if they mention the operator-identity story

- [ ] **Step 1: Update `config.toml`**

Edit `config.toml`. Replace the `[me]` block with:

```toml
[me]
# Identity used in the generated wiki for the "Me"-labeled sender.
# sender_label is the literal label Signal export uses for the exporter's own messages.
sender_label = "Me"
slug = "thomas-martin"
name = "Thomas Martin"

# Optional: occurrences of these patterns in message bodies and quoted text are
# scrubbed at ingest and replaced with `name` (multi-token patterns) or the first
# token of `name` (single-token patterns). Empty list = no scrubbing.
# Word-boundary anchored, case-insensitive, case-preserved replacement.
real_names = []
```

Do NOT commit a populated `real_names` to git — it's per-developer. Users add their real-name aliases to their local `config.toml` (which is gitignored at the values level — actually `config.toml` is tracked, so they should treat real_names as a personal override and not commit it). Add a `.gitignore` note if needed.

Wait — re-check: is `config.toml` tracked?

```bash
git check-ignore config.toml
```

(If it's tracked, add a brief note in CLAUDE.md telling users to set this locally and not commit the populated list. If it's gitignored, no action.)

- [ ] **Step 2: Update `CLAUDE.md` (and mirror to `AGENTS.md`)**

In `CLAUDE.md`, add to the "Standing conventions" list (after the existing `[me]` mention if any, or near the top of conventions):

```markdown
- **Operator-identity scrubbing.** `config.toml [me].real_names` is a per-developer list of plain-string patterns (e.g., `["Ugo", "Ugo Bataillard"]`) that are scrubbed from message bodies during ingest, replaced with `[me].name` (or its first token, for single-token patterns). The scrubber is word-boundary anchored, case-insensitive, case-preserved. Set this locally; the committed default is `[]`. Without it, the other party's references to you by your real name leak into `brain/<src>/` and break the pseudonym.
```

Mirror the same paragraph into `AGENTS.md` (if it exists at the repo root; the project mirrors them).

- [ ] **Step 3: Commit**

```bash
git add config.toml CLAUDE.md AGENTS.md
git commit -m "docs(anonymize): config + convention note for [me].real_names"
```

---

## Task 5: Smoke-test acceptance

**Files:** none modified — this is a verification task.

- [ ] **Step 1: Set up real-name aliases locally**

In your local (uncommitted) `config.toml`:

```toml
[me]
real_names = ["Ugo", "Ugo Bataillard"]
```

- [ ] **Step 2: Clean previous state**

```bash
rm -rf brain/SébastienBéal/
```

- [ ] **Step 3: Run the orchestrator skill end-to-end**

From inside Claude Code, invoke the `signal-brain-build` skill on the SébastienBéal source. Let it run all 14 steps.

- [ ] **Step 4: Verify acceptance criterion 1 — real name absent**

```bash
grep -ri "ugo" brain/SébastienBéal/ | grep -v "^Binary file" | wc -l
```

Expected: `0`.

If non-zero, inspect the matches. They should NOT include any from message body content — only acceptable matches (if any) are unrelated tokens like "augustaugu" in random text. If a real-name leak shows up, the scrubber failed somewhere; debug before claiming the PR done.

- [ ] **Step 5: Verify acceptance criterion 2 — pseudonym still greppable**

```bash
grep -ri "thomas" brain/SébastienBéal/ | wc -l
```

Expected: non-zero (sender label, slug, and any replaced text contribute hits).

- [ ] **Step 6: Verify acceptance criterion 3 — word-boundary correctness**

Grep for any text that contains "thomas" with a leading or trailing letter that would indicate a corrupted boundary match (e.g., `Hthomas`):

```bash
grep -riE "[A-Za-z]thomas|thomas[A-Za-z]" brain/SébastienBéal/ | wc -l
```

Expected: `0`.

- [ ] **Step 7: Verify acceptance criterion 5 — hash stability across runs**

```bash
cp brain/SébastienBéal/data/manifest.json /tmp/manifest-before.json
signal-brain ingest --plan --source SébastienBéal
signal-brain ingest --finalize --source SébastienBéal
diff /tmp/manifest-before.json brain/SébastienBéal/data/manifest.json
```

Expected: no diff (or only timestamp-trivial diff). The content_hashes dict must be identical.

- [ ] **Step 8: Open the PR**

```bash
git push -u origin feat/anonymize-ingest
gh pr create --title "feat: anonymize operator identity at ingest" --body "$(cat <<'EOF'
## Summary

Scrubs the operator's real-name aliases out of message bodies during ingest so they never land under `brain/<src>/`. Pseudonym (`thomas-martin` / "Thomas Martin") remains fully greppable.

- New `scripts/signal_brain/anonymize.py` exposes `compile_scrubber(real_names, replacement_full)` with word-boundary, case-insensitive, case-preserved replacement and longest-match-first semantics.
- `build_msg_index` accepts an optional `scrub` callable; applied to `body` and `quote`.
- `[me].real_names` in `config.toml` (default `[]`) controls the patterns; `[me].name` provides the pseudonym.

Spec: `docs/superpowers/specs/2026-05-20-anonymize-raw-ingest.md`

## Test plan

- [ ] `pytest -q` is green.
- [ ] Smoke test on SébastienBéal export: `grep -ri "ugo" brain/SébastienBéal/` returns 0 hits.
- [ ] `grep -ri "thomas" brain/SébastienBéal/` still returns hits.
- [ ] No corrupted-boundary matches (e.g., `Hthomas`).
- [ ] Two consecutive `ingest --plan` runs produce identical `manifest.json` content_hashes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist

After implementing all tasks, walk through the spec section by section:

1. **Spec coverage:**
   - Real name absent from `brain/<src>/` → Task 5 step 4.
   - Pseudonym still greppable → Task 5 step 5.
   - Word-boundary correctness → Tasks 1 (unit) + 5 step 6 (smoke).
   - Defaults inert → Task 1 (`test_empty_real_names_returns_identity`) + Task 2 (`test_build_msg_index_scrubber_default_is_identity`).
   - Hash stability → Task 5 step 7.

2. **Placeholder scan:** none — every code block is complete.

3. **Type consistency:** `compile_scrubber(list[str], str) -> Callable[[str], str]` is used identically in Task 1 (unit tests), Task 2 (msg_index wiring), and Task 3 (ingest wiring). `build_msg_index(...) -> int` signature is preserved (the `scrub` kwarg is keyword-only and defaults to `None`).

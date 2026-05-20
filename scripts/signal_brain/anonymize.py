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
    - matched's first character is uppercase → preserve the replacement's own
      casing (which is expected to already be titlecase / properly capitalized,
      e.g. "Thomas" or "Thomas Martin"). The first character is force-upper so
      that lowercase replacements still capitalize correctly when needed.
    - otherwise (all lowercase or no leading letter) → lowercase replacement.
    """
    if matched.isupper() and any(c.isalpha() for c in matched):
        return replacement.upper()
    if matched[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
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

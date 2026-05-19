"""Cross-cut page generation: agreements / disagreements / patterns / empirical pool."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


CROSS_SYSTEM = """Generate a "cross-cut" page: a pattern observed across multiple bursts/arcs.

Constraints:
- English prose. French quotes verbatim in citations.
- Every instance cites a message: [Bnnnn#mN].
- Output body only. Sections required, in order:
  ## Overview
  ## Instances   (bullet list, each citing a message)
  ## Related     (placeholder)
"""


CROSS_USER = """Cross-cut slug: {slug}  (title: {title})

Instances summary (deduplicated, with citations):
{instances_summary}

Write the page body."""


def generate_cross_page(*, slug: str, title: str, instances_summary: str, llm) -> str:
    body = llm.complete(
        CROSS_SYSTEM,
        CROSS_USER.format(slug=slug, title=title, instances_summary=instances_summary),
        max_tokens=3000,
    ).text.strip()
    fm = {"type": "cross", "slug": slug, "title": title,
          "last_touched": date.today().isoformat()}
    validate_page("cross", fm, body)
    return render_page(fm, body)

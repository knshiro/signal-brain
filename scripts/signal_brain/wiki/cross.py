"""Cross-cut page generation — plan/finalize split.

Cross pages cover agreements / disagreements / rhetorical patterns / empirical pool.
"""
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


PAGE_RESPONSE_SCHEMA = {"required": ["body"], "types": {"body": "str"}}


def build_cross_prompts(*, slug: str, title: str, instances_summary: str
                        ) -> tuple[str, str, dict, dict]:
    """Return (system_prompt, user_prompt, response_schema, planned_frontmatter)."""
    user = CROSS_USER.format(slug=slug, title=title, instances_summary=instances_summary)
    fm = {"type": "cross", "slug": slug, "title": title,
          "last_touched": date.today().isoformat()}
    return CROSS_SYSTEM, user, PAGE_RESPONSE_SCHEMA, fm


def render_cross_page(planned_fm: dict, body: str) -> str:
    validate_page("cross", planned_fm, body)
    return render_page(planned_fm, body)

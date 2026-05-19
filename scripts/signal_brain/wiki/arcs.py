"""Arc page generation — narrative summary of a debate arc. Plan/finalize split."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


ARC_SYSTEM = """Generate an "arc" page: narrative of a multi-burst debate arc.

Constraints:
- English prose. French quotes verbatim in citations.
- Every key turn cites a message: [Bnnnn#mN].
- Output body only. Sections required, in order:
  ## Question at stake
  ## Opening positions
  ## Key turns        (chronological bullet list with citations)
  ## Concessions & ground gained
  ## Why unresolved   (or "Why resolved")
  ## Related          (placeholder)
"""


ARC_USER = """Arc id: {arc_id}, slug: {slug}
Period: {period}
Primary topic: {primary_topic}
Bursts in this arc: {bursts}

Full per-burst summaries:
{bursts_summary}

Write the arc page body."""


PAGE_RESPONSE_SCHEMA = {"required": ["body"], "types": {"body": "str"}}


def build_arc_prompts(*, arc_id: str, slug: str, period: list[str], bursts: list[str],
                      primary_topic: str, bursts_summary: str,
                      status: str = "unresolved",
                      turning_points: list[str] | None = None
                      ) -> tuple[str, str, dict, dict]:
    """Return (system_prompt, user_prompt, response_schema, planned_frontmatter)."""
    user = ARC_USER.format(
        arc_id=arc_id, slug=slug, period=period, primary_topic=primary_topic,
        bursts=bursts, bursts_summary=bursts_summary,
    )
    fm = {
        "type": "arc", "id": arc_id, "slug": slug,
        "period": period, "bursts": bursts,
        "primary_topic": primary_topic, "status": status,
        "turning_points": turning_points or [],
        "last_touched": date.today().isoformat(),
    }
    return ARC_SYSTEM, user, PAGE_RESPONSE_SCHEMA, fm


def render_arc_page(planned_fm: dict, body: str) -> str:
    validate_page("arc", planned_fm, body)
    return render_page(planned_fm, body)

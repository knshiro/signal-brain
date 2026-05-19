"""Arc page generation — narrative summary of a debate arc."""
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


def generate_arc_page(*, arc_id: str, slug: str, period: list[str], bursts: list[str],
                     primary_topic: str, bursts_summary: str, llm,
                     status: str = "unresolved",
                     turning_points: list[str] | None = None) -> str:
    user = ARC_USER.format(
        arc_id=arc_id, slug=slug, period=period, primary_topic=primary_topic,
        bursts=bursts, bursts_summary=bursts_summary,
    )
    body = llm.complete(ARC_SYSTEM, user, max_tokens=4000).text.strip()
    fm = {
        "type": "arc", "id": arc_id, "slug": slug,
        "period": period, "bursts": bursts,
        "primary_topic": primary_topic, "status": status,
        "turning_points": turning_points or [],
        "last_touched": date.today().isoformat(),
    }
    validate_page("arc", fm, body)
    return render_page(fm, body)

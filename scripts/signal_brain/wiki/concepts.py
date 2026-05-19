"""Concept page generation."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


CONCEPT_SYSTEM = """Generate a "concept" page for a debate wiki.

Constraints:
- English prose. French quotes preserved verbatim in citations.
- Every non-trivial claim cites at least one message: [Bnnnn#mN].
- Output body only. Sections required, in order:
  ## What's at stake
  ## Sub-questions
  ## Empirical anchors  (list concrete examples cited in the conversation: numbers, historical events)
  ## Positions on this concept  (list links like [[positions/<holder>--<slug>]])
  ## Related  (placeholder: "(auto-maintained — see link pass)")
"""


CONCEPT_USER = """Concept slug: {slug}
Aliases: {aliases}
Contested: {contested}
Sources count: {sources_count}

Conversation summary on this topic:
{bursts_summary}

Write the page body."""


def generate_concept_page(*, slug: str, aliases: list[str], contested: bool,
                          sources_count: int, bursts_summary: str, llm) -> str:
    user = CONCEPT_USER.format(
        slug=slug, aliases=", ".join(aliases), contested=contested,
        sources_count=sources_count, bursts_summary=bursts_summary,
    )
    body = llm.complete(CONCEPT_SYSTEM, user, max_tokens=3000).text.strip()
    fm = {
        "type": "concept",
        "slug": slug,
        "aliases": aliases,
        "related": [],
        "contested": contested,
        "sources_count": sources_count,
        "last_touched": date.today().isoformat(),
    }
    validate_page("concept", fm, body)
    return render_page(fm, body)

"""People (entity) page generation."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


PERSON_SYSTEM = """You generate a "person" page for a Karpathy-style debate wiki.

Constraints:
- English prose throughout.
- Preserve French verbatim in quoted citations.
- Every non-trivial claim cites at least one message in the form [Bnnnn#mN].
- Output the body only — frontmatter is added by the caller.
- Sections required, in order:
  ## Background
  ## Style & drivers
  ## Key positions
  ## Recurring moves
  ## Open tensions
  ## Related

- "Related" should be a single placeholder line: "(auto-maintained — see link pass)".
"""


PERSON_USER = """Person: {name}  (slug: {slug}, relation: {relation})
Sources count (messages by/about): {sources_count}

Conversation summary across all bursts featuring this person:
{bursts_summary}

Write the page body."""


def generate_person_page(*, slug: str, name: str, relation: str,
                         bursts_summary: str, sources_count: int, llm,
                         drivers: list[str] | None = None,
                         tics: list[str] | None = None) -> str:
    user = PERSON_USER.format(
        slug=slug, name=name, relation=relation,
        bursts_summary=bursts_summary, sources_count=sources_count,
    )
    body = llm.complete(PERSON_SYSTEM, user, max_tokens=3000).text.strip()
    fm = {
        "type": "person",
        "slug": slug,
        "name": name,
        "relation": relation,
        "languages": ["fr", "en"],
        "drivers": drivers or [],
        "conversational-tics": tics or [],
        "sources_count": sources_count,
        "last_touched": date.today().isoformat(),
    }
    validate_page("person", fm, body)
    return render_page(fm, body)

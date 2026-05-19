"""People (entity) page generation — plan/finalize split."""
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


PAGE_RESPONSE_SCHEMA = {"required": ["body"], "types": {"body": "str"}}


def build_person_prompts(*, slug: str, name: str, relation: str,
                         bursts_summary: str, sources_count: int,
                         drivers: list[str] | None = None,
                         tics: list[str] | None = None) -> tuple[str, str, dict, dict]:
    """Return (system_prompt, user_prompt, response_schema, planned_frontmatter)."""
    user = PERSON_USER.format(
        slug=slug, name=name, relation=relation,
        bursts_summary=bursts_summary, sources_count=sources_count,
    )
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
    return PERSON_SYSTEM, user, PAGE_RESPONSE_SCHEMA, fm


def render_person_page(planned_fm: dict, body: str) -> str:
    validate_page("person", planned_fm, body)
    return render_page(planned_fm, body)

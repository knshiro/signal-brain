"""Position page generation — the page type unique to debate wikis."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


POSITION_SYSTEM = """Generate a "position" page: one person's stance on one concept.

Constraints:
- English prose. French quotes verbatim in citations.
- Every claim cites at least one message: [Bnnnn#mN].
- Stay grounded in what THIS holder actually said. Don't invent positions.
- Output body only. Sections required, in order:
  ## Core claim         (one sentence)
  ## Reasoning chain    (numbered steps; cite as you go)
  ## Examples / evidence cited
  ## Concessions made   (places this holder gave ground)
  ## Tensions with own other positions  (lint candidate; empty if none yet)
  ## Evolution timeline (dated turns: date — turn — citation)
  ## Counter-arguments faced  (strongest moves by the other party)
  ## Related  (placeholder: "(auto-maintained — see link pass)")
"""


POSITION_USER = """Holder: {holder}
Concept: {concept}
Stance (1-sentence summary the caller computed): {stance}
Confidence: {confidence}
First seen: {first_seen}
Last seen: {last_seen}
Evolution: {evolution}
Sources count: {sources_count}

What this holder said on this topic across the conversation:
{bursts_summary}

What the counterpart said back (for counter-arguments section):
{counterpart_summary}

Write the page body."""


def generate_position_page(*, holder: str, concept: str, stance: str,
                           confidence: str, first_seen: str, last_seen: str,
                           evolution: str, sources_count: int,
                           bursts_summary: str, counterpart_summary: str,
                           llm) -> str:
    user = POSITION_USER.format(
        holder=holder, concept=concept, stance=stance, confidence=confidence,
        first_seen=first_seen, last_seen=last_seen, evolution=evolution,
        sources_count=sources_count, bursts_summary=bursts_summary,
        counterpart_summary=counterpart_summary,
    )
    body = llm.complete(POSITION_SYSTEM, user, max_tokens=3500).text.strip()
    fm = {
        "type": "position",
        "holder": holder,
        "concept": concept,
        "stance": stance,
        "confidence": confidence,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "evolution": evolution,
        "sources_count": sources_count,
        "last_touched": date.today().isoformat(),
    }
    validate_page("position", fm, body)
    return render_page(fm, body)

"""Page schemas, parse/render, validation."""
from __future__ import annotations
import re
import yaml


class SchemaError(Exception):
    pass


REQUIRED_FRONTMATTER: dict[str, list[str]] = {
    "person": ["type", "slug", "name"],
    "concept": ["type", "slug", "contested"],
    "position": ["type", "holder", "concept", "stance", "confidence",
                 "first_seen", "last_seen", "evolution", "sources_count"],
    "arc": ["type", "id", "slug", "period", "primary_topic", "status", "bursts"],
    "cross": ["type", "slug"],
}


REQUIRED_SECTIONS: dict[str, list[str]] = {
    "person": ["Background", "Style & drivers", "Key positions", "Recurring moves", "Open tensions", "Related"],
    "concept": ["What's at stake", "Sub-questions", "Empirical anchors", "Positions on this concept", "Related"],
    "position": ["Core claim", "Reasoning chain", "Examples / evidence cited",
                 "Concessions made", "Tensions with own other positions",
                 "Evolution timeline", "Counter-arguments faced", "Related"],
    "arc": ["Question at stake", "Opening positions", "Key turns",
            "Concessions & ground gained", "Why unresolved", "Related"],
    "cross": ["Overview", "Instances", "Related"],
}


_FM_RE = re.compile(r"^---\n(.*?)\n---[ \t]*\n(.*)$", re.DOTALL)


def parse_page(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        raise SchemaError("Missing or malformed frontmatter block")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).lstrip()
    return fm, body


def render_page(frontmatter: dict, body: str) -> str:
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{fm}\n---\n\n{body.rstrip()}\n"


def validate_page(page_type: str, frontmatter: dict, body: str) -> None:
    if page_type not in REQUIRED_FRONTMATTER:
        raise SchemaError(f"Unknown page type: {page_type}")
    missing_fm = [k for k in REQUIRED_FRONTMATTER[page_type] if k not in frontmatter]
    if missing_fm:
        raise SchemaError(f"Missing frontmatter fields: {missing_fm}")
    found = set(re.findall(r"^##\s+(.+)$", body, re.MULTILINE))
    missing_sections = [s for s in REQUIRED_SECTIONS[page_type] if s not in found]
    if missing_sections:
        raise SchemaError(f"Missing sections: {missing_sections}")

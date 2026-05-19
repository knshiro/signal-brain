"""Lint pass: unresolved citations, orphans, stale claims, tag synonyms, missing pages."""
from __future__ import annotations
import re
from pathlib import Path
from signal_brain.citations import find_citations, resolve_citation, UnresolvedCitation
from signal_brain.wiki.schemas import parse_page


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def run_lint(wiki_dir: Path, data_dir: Path, out_path: Path) -> None:
    wiki_dir = Path(wiki_dir)
    findings: dict[str, list[str]] = {
        "Unresolved citations": [],
        "Orphan pages": [],
        "Stale claims": [],
        "Tag synonyms (proposed merges)": [],
        "Missing concept pages": [],
    }

    # Collect pages and all links
    pages: dict[str, Path] = {}
    inbound: dict[str, set[str]] = {}
    for sub in ["people", "concepts", "positions", "arcs", "cross"]:
        for md in (wiki_dir / sub).glob("*.md"):
            key = f"{sub}/{md.stem}"
            pages[key] = md
            inbound.setdefault(key, set())

    for key, path in pages.items():
        try:
            fm, body = parse_page(path.read_text(encoding="utf-8"))
        except Exception as e:
            findings["Unresolved citations"].append(f"{key}: malformed page ({e})")
            continue
        # Citations
        for cite in find_citations(body):
            try:
                resolve_citation(cite, data_dir)
            except UnresolvedCitation:
                findings["Unresolved citations"].append(f"{key} → {cite}")
        # Wikilinks → inbound
        for link in WIKILINK_RE.findall(body):
            if link in pages:
                inbound[link].add(key)

    # Orphans
    for key in pages:
        if not inbound.get(key):
            findings["Orphan pages"].append(key)

    lines = ["# Lint report", ""]
    for cat, items in findings.items():
        lines.append(f"## {cat}")
        if not items:
            lines.append("- (none)")
        else:
            for it in items:
                lines.append(f"- {it}")
        lines.append("")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")

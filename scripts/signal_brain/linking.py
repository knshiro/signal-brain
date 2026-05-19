"""Linking pass: Stage 1 deterministic + Stage 2 LLM lateral."""
from __future__ import annotations
import json
from pathlib import Path
from signal_brain.wiki.schemas import parse_page, render_page


RELATED_HEADING = "## Related"
RELATED_NOTE = "<!-- auto-maintained by link pass; do not hand-edit -->"


def _replace_related_block(body: str, links: list[str]) -> str:
    """Replace the `## Related` section (until next heading or EOF) with the given links."""
    lines = body.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == RELATED_HEADING:
            out.append(RELATED_HEADING)
            out.append(RELATED_NOTE)
            for link in sorted(set(links)):
                out.append(f"- {link}")
            # skip until next H2 or EOF
            i += 1
            while i < len(lines) and not lines[i].startswith("## "):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def write_related_blocks(links_by_path: dict[Path, list[str]]) -> None:
    for path, links in links_by_path.items():
        page = Path(path).read_text(encoding="utf-8")
        fm, body = parse_page(page)
        new_body = _replace_related_block(body, links)
        Path(path).write_text(render_page(fm, new_body), encoding="utf-8")


def _scan_pages(wiki_dir: Path) -> dict[Path, dict]:
    out: dict[Path, dict] = {}
    for sub in ["people", "concepts", "positions", "arcs", "cross"]:
        for md in (Path(wiki_dir) / sub).glob("*.md"):
            try:
                fm, body = parse_page(md.read_text(encoding="utf-8"))
            except Exception:
                continue
            out[md] = {"fm": fm, "body": body, "sub": sub, "stem": md.stem}
    return out


def build_deterministic_graph(wiki_dir: Path) -> dict[Path, set[str]]:
    pages = _scan_pages(wiki_dir)
    links: dict[Path, set[str]] = {p: set() for p in pages}
    # Index by (type, slug)
    by_slug = {(p["fm"].get("type"), p["fm"].get("slug") or p["stem"]): path
               for path, p in pages.items()}
    for path, p in pages.items():
        fm = p["fm"]
        t = fm.get("type")
        if t == "position":
            concept = fm.get("concept")
            holder = fm.get("holder")
            ref_pos = f"[[positions/{path.stem}]]"
            if concept:
                cpath = by_slug.get(("concept", concept))
                links[path].add(f"[[concepts/{concept}]]")
                if cpath:
                    links[cpath].add(ref_pos)
            if holder:
                ppath = by_slug.get(("person", holder))
                links[path].add(f"[[people/{holder}]]")
                if ppath:
                    links[ppath].add(ref_pos)
        elif t == "arc":
            primary = fm.get("primary_topic")
            ref_arc = f"[[arcs/{path.stem}]]"
            if primary:
                cpath = by_slug.get(("concept", primary))
                links[path].add(f"[[concepts/{primary}]]")
                if cpath:
                    links[cpath].add(ref_arc)
            # arc ↔ position via shared concept holders
            for pos_path, pp in pages.items():
                if pp["fm"].get("type") == "position" and pp["fm"].get("concept") == primary:
                    links[path].add(f"[[positions/{pos_path.stem}]]")
                    links[pos_path].add(ref_arc)
    return links


def run_stage1(wiki_dir: Path) -> None:
    links = build_deterministic_graph(wiki_dir)
    write_related_blocks({p: sorted(s) for p, s in links.items()})


STAGE2_SYSTEM = """You are the link-pass agent for a debate wiki. Given a page and the wiki's index, propose lateral links — pages clearly related to this one that the deterministic pass might miss.

Output VALID JSON. No prose around it. Format:
{"links": ["[[concepts/...]]", "[[cross/...]]", ...]}

Rules:
- Only propose wiki links that actually exist in the index.
- Cap at 6 lateral links per page.
- Prefer Cross pages and lateral concept-concept / position-position links.
- Do not propose self-links.
"""


STAGE2_USER = """Current page ({page_path}):
---
{page_body_snippet}
---

Index of all pages:
{index_excerpt}

Propose lateral links."""


def run_stage2(wiki_dir: Path, llm, data_dir: Path | None = None) -> None:
    wiki_dir = Path(wiki_dir)
    pages = _scan_pages(wiki_dir)
    index_excerpt = (wiki_dir / "index.md").read_text(encoding="utf-8") if (wiki_dir / "index.md").exists() else ""
    stage1 = build_deterministic_graph(wiki_dir)
    final: dict[Path, set[str]] = {p: set(stage1.get(p, set())) for p in pages}
    self_links = {p: f"[[{pages[p]['sub']}/{p.stem}]]" for p in pages}
    for path, p in pages.items():
        body_snippet = "\n".join(p["body"].splitlines()[:80])
        result = llm.complete_json(
            STAGE2_SYSTEM,
            STAGE2_USER.format(
                page_path=f"{p['sub']}/{path.stem}",
                page_body_snippet=body_snippet,
                index_excerpt=index_excerpt,
            ),
        )
        for link in result.get("links", []):
            if link == self_links[path]:
                continue
            final[path].add(link)
    write_related_blocks({p: sorted(s) for p, s in final.items()})

    # Snapshot graph
    graph = [{"page": str(p.relative_to(wiki_dir)), "links": sorted(s)}
             for p, s in final.items()]
    if data_dir is None:
        data_dir = wiki_dir.parent / "data"   # legacy fallback
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "link_graph.jsonl").write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in graph) + "\n",
        encoding="utf-8",
    )

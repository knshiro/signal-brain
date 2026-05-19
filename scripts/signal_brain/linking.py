"""Linking pass: Stage 1 deterministic + Stage 2 lateral (plan/finalize).

Stage 1 builds a deterministic graph from page frontmatter and writes
`## Related` blocks directly. Stage 2 is two-phase: `run_stage2_plan` emits a
lateral-link todo row per page; `run_stage2_finalize` reads matching done rows,
filters invalid links, merges with the Stage 1 graph, and writes the final
graph + `## Related` blocks. Neither phase calls an LLM directly.
"""
from __future__ import annotations
import json
from pathlib import Path
from signal_brain.wiki.schemas import parse_page, render_page
from signal_brain.worklist import (
    WorklistError,
    emit,
    load_done,
    load_todo,
    validate_response,
)


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


LATERAL_LINK_RESPONSE_SCHEMA = {
    "required": ["links"],
    "types": {"links": "list"},
}


MAX_LATERAL_LINKS = 6


def _is_valid_link(link) -> bool:
    return isinstance(link, str) and link.startswith("[[") and link.endswith("]]")


def run_stage2_plan(wiki_dir: Path, todo_path: Path, data_dir: Path) -> dict:
    """Plan phase: scan pages, emit one lateral-link todo per page. No LLM."""
    wiki_dir = Path(wiki_dir)
    pages = _scan_pages(wiki_dir)
    index_excerpt = (
        (wiki_dir / "index.md").read_text(encoding="utf-8")
        if (wiki_dir / "index.md").exists() else ""
    )
    links_planned = 0
    for path, p in pages.items():
        body_snippet = "\n".join(p["body"].splitlines()[:80])
        page_path = f"{p['sub']}/{path.stem}"
        user = STAGE2_USER.format(
            page_path=page_path,
            page_body_snippet=body_snippet,
            index_excerpt=index_excerpt,
        )
        emit(
            todo_path,
            stage="lateral-link",
            kind="page-link",
            system=STAGE2_SYSTEM,
            user=user,
            response_schema=LATERAL_LINK_RESPONSE_SCHEMA,
            context={
                "page_path": str(path),
                "sub": p["sub"],
                "stem": path.stem,
            },
        )
        links_planned += 1
    return {"links_planned": links_planned}


def run_stage2_finalize(
    wiki_dir: Path,
    todo_path: Path,
    done_path: Path,
    data_dir: Path,
) -> dict:
    """Finalize phase: merge done rows with Stage 1, write graph + related blocks."""
    wiki_dir = Path(wiki_dir)
    data_dir = Path(data_dir)
    todos = load_todo(todo_path)
    done_by_job = load_done(done_path)
    stage1 = build_deterministic_graph(wiki_dir)
    final: dict[Path, set[str]] = {p: set(stage1.get(p, set())) for p in stage1}

    missing: list[str] = []
    invalid: list[str] = []
    failed_rows: list[dict] = []

    for todo in todos:
        ctx = todo.get("context", {})
        page_path = Path(ctx.get("page_path", ""))
        sub = ctx.get("sub", "")
        stem = ctx.get("stem", "")
        self_link = f"[[{sub}/{stem}]]"
        if page_path not in final:
            final[page_path] = set()
        done = done_by_job.get(todo["job_id"])
        if done is None:
            missing.append(todo["job_id"])
            continue
        resp = done.get("response", {})
        try:
            validate_response(resp, todo["response_schema"])
        except WorklistError as e:
            invalid.append(todo["job_id"])
            failed_rows.append({
                "job_id": todo["job_id"],
                "page_path": str(page_path),
                "error": str(e),
                "response": resp,
            })
            continue
        kept: list[str] = []
        for link in resp.get("links", []):
            if not _is_valid_link(link):
                continue
            if link == self_link:
                continue
            kept.append(link)
            if len(kept) >= MAX_LATERAL_LINKS:
                break
        for link in kept:
            final[page_path].add(link)

    write_related_blocks({p: sorted(s) for p, s in final.items()})

    data_dir.mkdir(parents=True, exist_ok=True)
    graph = [
        {"page": str(p.relative_to(wiki_dir)), "links": sorted(s)}
        for p, s in final.items()
    ]
    (data_dir / "link_graph.jsonl").write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in graph) + ("\n" if graph else ""),
        encoding="utf-8",
    )

    if failed_rows:
        failed_path = data_dir / "link.failed.jsonl"
        failed_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in failed_rows) + "\n",
            encoding="utf-8",
        )

    links_written = sum(len(s) for s in final.values())
    return {
        "links_written": links_written,
        "missing": missing,
        "invalid": invalid,
    }

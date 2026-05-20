"""Wiki page build orchestration — plan/finalize.

`plan_pages` decides which pages exist (deterministic, unchanged). `build_wiki_plan`
walks the plan and emits one synthesis todo row per page via the worklist module.
`build_wiki_finalize` reads the done file, validates each body against the page
schema, and writes the .md file. Schema failures land in `synthesis.failed.jsonl`
without aborting the rest of the build.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

from signal_brain.sources import slugify
from signal_brain.wiki.schemas import SchemaError
from signal_brain.wiki.people import build_person_prompts, render_person_page
from signal_brain.wiki.concepts import build_concept_prompts, render_concept_page
from signal_brain.wiki.positions import build_position_prompts, render_position_page
from signal_brain.wiki.arcs import build_arc_prompts, render_arc_page
from signal_brain.wiki.cross import build_cross_prompts, render_cross_page
from signal_brain.worklist import emit, load_done, load_todo


def _sender_to_identity(sender: str, me: dict) -> tuple[str, str, str]:
    """Return (slug, name, relation) for a sender label."""
    if sender == me["sender_label"]:
        return me["slug"], me["name"], "Me"
    return slugify(sender), sender, "Friend"


def plan_pages(bursts: list[dict], chunks: list[dict], arcs: list[dict],
               *, me: dict, concepts: list[str]) -> dict:
    """Decide which pages should exist. Returns {"pages": {key: spec}}.

    Concept and position pages are AI-decided: a concept page is planned for
    each slug in `concepts` (the taxonomy's page-worthy topics) that is backed
    by at least one burst. Topic counting considers every topic on a burst (the
    full `topics` list), not just `primary` — a burst that substantively covers
    a topic contributes to it even when it is not the single dominant one.

    Args:
        me: dict with keys sender_label, slug, name. Identifies the "Me" sender.
        concepts: taxonomy `concepts` list — the AI's judgment of which topic
            slugs are page-worthy. An empty list plans no concept/position pages.
    """
    chunk_by_burst = {c["burst_id"]: c for c in chunks}
    topic_bursts: dict[str, list[str]] = defaultdict(list)
    person_bursts: dict[str, list[str]] = defaultdict(list)
    person_meta: dict[str, dict] = {}
    person_topic_bursts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for b in bursts:
        c = chunk_by_burst.get(b["id"])
        if not c:
            continue
        topics = set(c.get("topics", []))
        for topic in topics:
            topic_bursts[topic].append(b["id"])
        for sender, n in b.get("senders", {}).items():
            if n == 0:
                continue
            slug, name, relation = _sender_to_identity(sender, me)
            if not slug:
                continue
            person_bursts[slug].append(b["id"])
            person_meta.setdefault(slug, {"name": name, "relation": relation})
            for topic in topics:
                person_topic_bursts[(slug, topic)].append(b["id"])

    pages: dict[str, dict] = {}
    for slug, bs in person_bursts.items():
        meta = person_meta[slug]
        pages[f"people/{slug}"] = {
            "slug": slug, "bursts": bs,
            "name": meta["name"], "relation": meta["relation"],
        }
    concept_set = set(concepts)
    for slug in concepts:
        bs = topic_bursts.get(slug)
        if not bs:
            continue
        pages[f"concepts/{slug}"] = {"slug": slug, "bursts": bs}
    for (holder, topic), bs in person_topic_bursts.items():
        if topic not in concept_set or not bs:
            continue
        pages[f"positions/{holder}--{topic}"] = {
            "holder": holder, "concept": topic, "bursts": bs,
        }
    for a in arcs:
        pages[f"arcs/{a['id']}-{a['slug'].split('-B')[0]}"] = {
            "arc_id": a["id"], "slug": a["slug"].split("-B")[0],
            "period": a["period"], "bursts": a["bursts"],
            "primary_topic": a["primary"], "status": a["status"],
        }
    return {"pages": pages}


def _summarize_bursts_for(burst_ids: list[str], chunks_by_id: dict[str, dict]) -> str:
    return "\n".join(
        f"- {bid} ({chunks_by_id[bid]['primary']}): {chunks_by_id[bid]['summary']}"
        for bid in burst_ids if bid in chunks_by_id
    )


_CROSS_SEEDS = [
    ("agreements", "Agreements"),
    ("disagreements", "Disagreements"),
    ("rhetorical-patterns", "Rhetorical patterns"),
    ("empirical-pool", "Empirical pool"),
]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_concepts(data_dir: Path) -> list[str]:
    """Read the `concepts` list from taxonomy.json. Empty list if absent or malformed."""
    path = Path(data_dir) / "taxonomy.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    concepts = data.get("concepts", [])
    return concepts if isinstance(concepts, list) else []


def build_wiki_plan(*, data_dir: Path, wiki_dir: Path, me: dict,
                    todo_path: Path) -> dict:
    """Plan phase: emit one synthesis todo per page that should exist. No LLM.

    Concept and position page selection is driven by the `concepts` list in
    `data_dir/taxonomy.json`. When that file is absent, `concepts` is empty and
    no concept/position pages are planned — a graceful degradation, not an error.
    """
    data_dir = Path(data_dir)
    wiki_dir = Path(wiki_dir)
    todo_path = Path(todo_path)
    for sub in ["people", "concepts", "positions", "arcs", "cross"]:
        (wiki_dir / sub).mkdir(parents=True, exist_ok=True)

    bursts = _load_jsonl(data_dir / "bursts.jsonl")
    chunks = _load_jsonl(data_dir / "chunks.jsonl")
    arcs = _load_jsonl(data_dir / "arcs.jsonl")
    chunks_by_id = {c["burst_id"]: c for c in chunks}
    concepts = _load_concepts(data_dir)

    plan = plan_pages(bursts, chunks, arcs, me=me, concepts=concepts)
    planned = 0

    for key, spec in plan["pages"].items():
        sub, name = key.split("/", 1)
        summary = _summarize_bursts_for(spec.get("bursts", []), chunks_by_id)
        out_path = wiki_dir / sub / f"{name}.md"
        if sub == "people":
            system, user, schema, fm = build_person_prompts(
                slug=spec["slug"], name=spec["name"], relation=spec["relation"],
                bursts_summary=summary, sources_count=len(spec["bursts"]),
            )
            page_type, kind = "person", "page-person"
        elif sub == "concepts":
            system, user, schema, fm = build_concept_prompts(
                slug=spec["slug"], aliases=[], contested=True,
                sources_count=len(spec["bursts"]), bursts_summary=summary,
            )
            page_type, kind = "concept", "page-concept"
        elif sub == "positions":
            system, user, schema, fm = build_position_prompts(
                holder=spec["holder"], concept=spec["concept"],
                stance="(see Core claim)", confidence="medium",
                first_seen=f"[{spec['bursts'][0]}#m1]",
                last_seen=f"[{spec['bursts'][-1]}#m1]",
                evolution="stable", sources_count=len(spec["bursts"]),
                bursts_summary=summary, counterpart_summary=summary,
            )
            page_type, kind = "position", "page-position"
        elif sub == "arcs":
            system, user, schema, fm = build_arc_prompts(
                arc_id=spec["arc_id"], slug=spec["slug"],
                period=spec["period"], bursts=spec["bursts"],
                primary_topic=spec["primary_topic"], bursts_summary=summary,
                status=spec["status"],
            )
            page_type, kind = "arc", "page-arc"
        else:
            continue
        emit(
            todo_path,
            stage="synthesis", kind=kind,
            system=system, user=user, response_schema=schema,
            context={"page_type": page_type,
                     "out_path": str(out_path), "frontmatter": fm},
        )
        planned += 1

    cross_instances = "\n".join(f"- {c['burst_id']}: {c['summary']}" for c in chunks[:20])
    for slug, title in _CROSS_SEEDS:
        out_path = wiki_dir / "cross" / f"{slug}.md"
        if out_path.exists():
            continue
        system, user, schema, fm = build_cross_prompts(
            slug=slug, title=title, instances_summary=cross_instances,
        )
        emit(
            todo_path,
            stage="synthesis", kind="page-cross",
            system=system, user=user, response_schema=schema,
            context={"page_type": "cross", "out_path": str(out_path), "frontmatter": fm},
        )
        planned += 1

    return {"pages_planned": planned}


_RENDERERS = {
    "person": render_person_page,
    "concept": render_concept_page,
    "position": render_position_page,
    "arc": render_arc_page,
    "cross": render_cross_page,
}


def build_wiki_finalize(*, data_dir: Path, wiki_dir: Path,
                        todo_path: Path, done_path: Path) -> dict:
    """Finalize phase: read done.jsonl, validate, write .md files. No LLM."""
    data_dir = Path(data_dir)
    wiki_dir = Path(wiki_dir)
    todo_path = Path(todo_path)
    done_path = Path(done_path)

    todos_by_job = {row["job_id"]: row for row in load_todo(todo_path)}
    done_by_job = load_done(done_path)
    failed_path = data_dir / "synthesis.failed.jsonl"

    pages_written = 0
    failed = 0
    missing: list[str] = []

    for job_id, todo in todos_by_job.items():
        done = done_by_job.get(job_id)
        if done is None:
            missing.append(job_id)
            continue
        ctx = todo.get("context", {})
        page_type = ctx.get("page_type")
        fm = ctx.get("frontmatter", {})
        out_path = Path(ctx.get("out_path", ""))
        body = done.get("response", {}).get("body", "")
        renderer = _RENDERERS.get(page_type)
        if renderer is None:
            failed += 1
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            with failed_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "job_id": job_id, "page_type": page_type,
                    "error": f"unknown page_type: {page_type!r}",
                    "body_snippet": body[:200],
                }, ensure_ascii=False) + "\n")
            continue
        try:
            rendered = renderer(fm, body)
        except SchemaError as e:
            failed += 1
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            with failed_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "job_id": job_id, "page_type": page_type,
                    "error": str(e), "body_snippet": body[:200],
                }, ensure_ascii=False) + "\n")
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        pages_written += 1

    return {"pages_written": pages_written, "failed": failed, "missing": missing}

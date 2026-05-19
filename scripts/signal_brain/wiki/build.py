"""Wiki page build orchestration: decide what pages to create, summarize bursts, generate."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
from signal_brain.sources import slugify
from signal_brain.wiki.people import generate_person_page
from signal_brain.wiki.concepts import generate_concept_page
from signal_brain.wiki.positions import generate_position_page
from signal_brain.wiki.arcs import generate_arc_page
from signal_brain.wiki.cross import generate_cross_page


def _sender_to_identity(sender: str, me: dict) -> tuple[str, str, str]:
    """Return (slug, name, relation) for a sender label."""
    if sender == me["sender_label"]:
        return me["slug"], me["name"], "Me"
    return slugify(sender), sender, "Friend"


def plan_pages(bursts: list[dict], chunks: list[dict], arcs: list[dict],
               min_concept_bursts: int, *, me: dict) -> dict:
    """Decide which pages should exist. Returns {"pages": {key: spec}}.

    Args:
        me: dict with keys sender_label, slug, name. Identifies the "Me" sender.
    """
    chunk_by_burst = {c["burst_id"]: c for c in chunks}
    topic_counts: dict[str, int] = defaultdict(int)
    topic_bursts: dict[str, list[str]] = defaultdict(list)
    person_bursts: dict[str, list[str]] = defaultdict(list)
    person_meta: dict[str, dict] = {}  # slug -> {name, relation}
    person_topic_bursts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for b in bursts:
        c = chunk_by_burst.get(b["id"])
        if not c:
            continue
        primary = c["primary"]
        topic_counts[primary] += 1
        topic_bursts[primary].append(b["id"])
        for sender, n in b.get("senders", {}).items():
            if n == 0:
                continue
            slug, name, relation = _sender_to_identity(sender, me)
            if not slug:
                continue
            person_bursts[slug].append(b["id"])
            person_meta.setdefault(slug, {"name": name, "relation": relation})
            person_topic_bursts[(slug, primary)].append(b["id"])

    pages: dict[str, dict] = {}
    for slug, bs in person_bursts.items():
        meta = person_meta[slug]
        pages[f"people/{slug}"] = {
            "slug": slug, "bursts": bs,
            "name": meta["name"], "relation": meta["relation"],
        }
    for topic, count in topic_counts.items():
        if count < min_concept_bursts:
            continue
        pages[f"concepts/{topic}"] = {"slug": topic, "bursts": topic_bursts[topic]}
    for (holder, topic), bs in person_topic_bursts.items():
        if topic_counts[topic] < min_concept_bursts:
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


def build_wiki(*, data_dir: Path, wiki_dir: Path, llm, me: dict,
               min_concept_bursts: int = 5) -> dict:
    data_dir = Path(data_dir)
    wiki_dir = Path(wiki_dir)
    for sub in ["people", "concepts", "positions", "arcs", "cross"]:
        (wiki_dir / sub).mkdir(parents=True, exist_ok=True)
    bursts = [json.loads(l) for l in (data_dir / "bursts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    chunks = [json.loads(l) for l in (data_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    arcs = [json.loads(l) for l in (data_dir / "arcs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] \
        if (data_dir / "arcs.jsonl").exists() else []
    chunks_by_id = {c["burst_id"]: c for c in chunks}

    plan = plan_pages(bursts, chunks, arcs, min_concept_bursts=min_concept_bursts, me=me)
    written: dict[str, str] = {}

    for key, spec in plan["pages"].items():
        sub, name = key.split("/", 1)
        summary = _summarize_bursts_for(spec.get("bursts", []), chunks_by_id)
        path = wiki_dir / sub / f"{name}.md"
        if sub == "people":
            page = generate_person_page(
                slug=spec["slug"], name=spec["name"], relation=spec["relation"],
                bursts_summary=summary, sources_count=len(spec["bursts"]), llm=llm,
            )
        elif sub == "concepts":
            page = generate_concept_page(
                slug=spec["slug"], aliases=[], contested=True,
                sources_count=len(spec["bursts"]), bursts_summary=summary, llm=llm,
            )
        elif sub == "positions":
            counterpart_summary = summary
            page = generate_position_page(
                holder=spec["holder"], concept=spec["concept"],
                stance="(see Core claim)", confidence="medium",
                first_seen=f"[{spec['bursts'][0]}#m1]",
                last_seen=f"[{spec['bursts'][-1]}#m1]",
                evolution="stable", sources_count=len(spec["bursts"]),
                bursts_summary=summary, counterpart_summary=counterpart_summary, llm=llm,
            )
        elif sub == "arcs":
            page = generate_arc_page(
                arc_id=spec["arc_id"], slug=spec["slug"],
                period=spec["period"], bursts=spec["bursts"],
                primary_topic=spec["primary_topic"], bursts_summary=summary, llm=llm,
                status=spec["status"],
            )
        else:
            continue
        path.write_text(page, encoding="utf-8")
        written[key] = str(path)

    # Seed cross pages
    for slug, title in [("agreements", "Agreements"), ("disagreements", "Disagreements"),
                        ("rhetorical-patterns", "Rhetorical patterns"),
                        ("empirical-pool", "Empirical pool")]:
        path = wiki_dir / "cross" / f"{slug}.md"
        if not path.exists():
            instances = "\n".join(f"- {c['burst_id']}: {c['summary']}" for c in chunks[:20])
            page = generate_cross_page(slug=slug, title=title,
                                       instances_summary=instances, llm=llm)
            path.write_text(page, encoding="utf-8")
            written[f"cross/{slug}"] = str(path)

    return {"pages_written": len(written), "paths": written}

"""L2a: per-burst topic tagging via LLM, with content-hash cache reuse."""
from __future__ import annotations
import json
from pathlib import Path
from signal_brain.bursts import burst_content_hash


def build_system_prompt(description: str = "") -> str:
    """System prompt for the tagger. `description` is an optional context hint."""
    context = f"\n\nContext: {description}." if description.strip() else ""
    return (
        "You are a topic tagger for a Signal conversation between two people. "
        "Tag each burst with 1-3 topics." + context + "\n\n"
        "Rules:\n"
        "- Output VALID JSON. No prose around it.\n"
        "- Output language: English (lowercase, kebab-case slugs).\n"
        "- Quotes in summaries must preserve the original source language.\n"
        "- \"primary\" is the single dominant topic.\n"
        "- \"summary\" is one sentence (<= 25 words) describing what was discussed, in English.\n"
    )


def build_user_prompt(burst_id: str, start: str, messages: str,
                     seed_tags: list[str] | None) -> str:
    """User prompt for a single burst. `seed_tags` is optional; empty means no priming."""
    seed_section = ""
    if seed_tags:
        seed_section = (
            "Seed tags (use when they fit; you may propose new ones if needed):\n"
            f"{', '.join(seed_tags)}\n\n"
        )
    return (
        f"{seed_section}"
        f"Burst {burst_id} ({start}):\n"
        f"---\n{messages}\n---\n\n"
        'Output JSON:\n{"topics": ["...", "..."], "primary": "...", "summary": "..."}'
    )


def _render_burst_for_tagging(burst: dict, all_messages: list[dict]) -> str:
    by_id = {m["msg_id"]: m for m in all_messages}
    lines = []
    for mid in burst["msg_ids"]:
        m = by_id.get(mid)
        if not m:
            continue
        body = (m.get("body") or "").strip().replace("\n", " ")
        if body:
            lines.append(f"{m['sender']}: {body}")
    return "\n".join(lines)


def tag_bursts(bursts: list[dict], all_messages: list[dict], llm,
               cache_by_id: dict[str, dict], out_path: Path,
               *, description: str = "",
               seed_tags: list[str] | None = None) -> dict[str, str]:
    """Tag bursts; reuse cache when hash matches. Returns id->hash map.

    Args:
        description: optional conversational-context hint included in the system prompt.
        seed_tags: optional priming vocabulary. Empty/None = LLM proposes freely.
    """
    system_prompt = build_system_prompt(description)
    out_rows = []
    new_hashes: dict[str, str] = {}
    for b in bursts:
        h = burst_content_hash(b, all_messages)
        new_hashes[b["id"]] = h
        cached = cache_by_id.get(b["id"])
        if cached and cached.get("hash") == h:
            out_rows.append({
                "burst_id": b["id"], "topics": cached["topics"],
                "primary": cached["primary"], "summary": cached["summary"],
            })
            continue
        user = build_user_prompt(
            burst_id=b["id"], start=b["start"],
            messages=_render_burst_for_tagging(b, all_messages),
            seed_tags=seed_tags,
        )
        result = llm.complete_json(system_prompt, user)
        out_rows.append({
            "burst_id": b["id"], "topics": result["topics"],
            "primary": result["primary"], "summary": result["summary"],
        })
    Path(out_path).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + "\n",
        encoding="utf-8",
    )
    return new_hashes


def load_chunks_as_cache(chunks_path: Path, hashes_by_id: dict[str, str]) -> dict[str, dict]:
    if not Path(chunks_path).exists():
        return {}
    cache = {}
    for line in Path(chunks_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cache[row["burst_id"]] = {
            "hash": hashes_by_id.get(row["burst_id"], ""),
            "topics": row["topics"], "primary": row["primary"], "summary": row["summary"],
        }
    return cache

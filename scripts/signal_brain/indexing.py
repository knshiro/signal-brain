"""Build index.md catalog, bootstrap brain root docs, append-only log.md."""
from __future__ import annotations
from pathlib import Path
from signal_brain.wiki.schemas import parse_page


BRAIN_README = """# Reading a brain folder

This file (mirrored as `CLAUDE.md`) tells an agent how to read any sibling `brain/<source>/` folder. Each `<source>/` is a self-contained record of one Signal conversation organised as a Karpathy-style wiki with citations back to exact messages.

## Folder layout

Inside each `brain/<source>/`:

- `index.md` — catalog of all pages with short summaries.
- `log.md` — chronological append-only record of updates.
- `lint-report.md` — last health check (citation/orphan flags).
- `data/` — machine layer (msg_index, bursts, chunks, arcs, manifest, link_graph). Use to resolve citations.
- `people/`, `concepts/`, `positions/`, `arcs/`, `cross/` — the wiki pages.

When asked a question, load `index.md` first, then the most-relevant pages from there.

## Page types

- `people/{slug}.md` — one entity. Frontmatter: `type, slug, name`. Sections: `Background`, `Style & drivers`, `Key positions`, `Recurring moves`, `Open tensions`, `Related`.
- `concepts/{slug}.md` — one topic. Frontmatter: `type, slug, contested`. Sections: `What's at stake`, `Sub-questions`, `Empirical anchors`, `Positions on this concept`, `Related`.
- `positions/{holder}--{concept}.md` — one person's stance on one concept (the page type Karpathy doesn't have). Frontmatter: `type, holder, concept, stance, confidence, first_seen, last_seen, evolution, sources_count`. Sections: `Core claim`, `Reasoning chain`, `Examples / evidence cited`, `Concessions made`, `Tensions with own other positions`, `Evolution timeline`, `Counter-arguments faced`, `Related`. Load these first when asked "what does X think about Y?".
- `arcs/A{nnn}-{slug}.md` — narrative summary of a multi-burst debate arc. Frontmatter: `type, id, slug, period, primary_topic, status, bursts`. Sections: `Question at stake`, `Opening positions`, `Key turns`, `Concessions & ground gained`, `Why unresolved`, `Related`.
- `cross/{slug}.md` — patterns observed across the corpus (`agreements`, `disagreements`, `rhetorical-patterns`, `empirical-pool`). Frontmatter: `type, slug`. Sections: `Overview`, `Instances`, `Related`.

## Citation format

Every non-trivial claim cites at least one message in the form `[Bnnnn#mN]`:
- `Bnnnn` — 4-digit zero-padded burst id (look up in `data/bursts.jsonl`).
- `mN` — 1-indexed position of the message within that burst's `msg_ids` array.

To resolve a citation, find the burst row, take the Nth element of its `msg_ids`, then look up that id in `data/msg_index.jsonl`.

## Naming and language

- All slugs are lowercase ASCII, kebab-case, no diacritics (`bjork`, not `björk`).
- Position-page slugs use a double-hyphen separator: `{holder}--{concept}`.
- Arc-page slugs are prefixed with their id: `A007-slug-here`.
- Wiki content is in English. Quoted source material is preserved verbatim in its original language.

## The `## Related` section

The `## Related` section at the bottom of every page is auto-maintained. Read it for traversal; do not hand-edit.

## Links

Inter-page references use `[[sub/name]]` wiki-link syntax. The link target maps to `brain/<source>/<sub>/<name>.md`.
"""


def bootstrap_brain_root(brain_root: Path) -> None:
    """Write the agent-facing reader's guide at brain/AGENTS.md and brain/CLAUDE.md.

    Idempotent: only writes if the target files are absent, so user edits are preserved.
    """
    brain_root = Path(brain_root)
    brain_root.mkdir(parents=True, exist_ok=True)
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = brain_root / name
        if not path.exists():
            path.write_text(BRAIN_README, encoding="utf-8")


def append_log(path: Path, entry: str) -> None:
    p = Path(path)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    if existing and not existing.endswith("\n\n"):
        existing = existing.rstrip("\n") + "\n\n"
    p.write_text(existing + entry.rstrip("\n") + "\n", encoding="utf-8")


def build_index(wiki_dir: Path, out_path: Path) -> None:
    wiki_dir = Path(wiki_dir)
    sections = {
        "People": [], "Concepts": [], "Positions": [],
        "Arcs": [], "Cross": [],
    }
    subdir_to_section = {
        "people": "People", "concepts": "Concepts", "positions": "Positions",
        "arcs": "Arcs", "cross": "Cross",
    }
    for sub, section in subdir_to_section.items():
        subpath = wiki_dir / sub
        if not subpath.exists():
            continue
        for md in sorted(subpath.glob("*.md")):
            try:
                fm, _ = parse_page(md.read_text(encoding="utf-8"))
            except Exception:
                continue
            name = md.stem
            label = fm.get("name") or fm.get("stance") or fm.get("title") or fm.get("slug") or name
            srcs = fm.get("sources_count", "?")
            last = fm.get("last_touched", "?")
            sections[section].append(f"- [[{sub}/{name}]] — {label}. ({srcs} msgs · {last})")
    lines = ["# Index", ""]
    for s, items in sections.items():
        if not items:
            continue
        lines.append(f"## {s}")
        lines.extend(items)
        lines.append("")
    Path(out_path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

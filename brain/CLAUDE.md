# Reading a brain folder

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

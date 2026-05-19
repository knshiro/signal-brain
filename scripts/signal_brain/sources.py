"""Source-conversation discovery and label slugification."""
from __future__ import annotations
import re
import unicodedata
from pathlib import Path


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(label: str) -> str:
    """Slugify a sender label: strip diacritics, lowercase, collapse non-alnum to hyphens.

    Examples:
        slugify("BjörkGuðmundsdóttir") == "bjorkgudmundsdottir"
        slugify("Marie-Claire D'Avignon") == "marie-claire-d-avignon"
        slugify("Me") == "me"
    """
    if not label:
        return ""
    # Decompose unicode (é -> e + combining accent), drop combining marks
    nfkd = unicodedata.normalize("NFKD", label)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    hyphenated = _NON_ALNUM.sub("-", lowered)
    return hyphenated.strip("-") or ""


def list_sources(out_root: Path) -> list[str]:
    """Return directory names under out/ that contain a data.json file.

    Sorted for determinism. Empty if out/ doesn't exist.
    """
    out_root = Path(out_root)
    if not out_root.is_dir():
        return []
    return sorted(
        p.name for p in out_root.iterdir()
        if p.is_dir() and (p / "data.json").is_file()
    )


class AmbiguousSource(Exception):
    pass


class NoSourceFound(Exception):
    pass


def resolve_source(name: str | None, out_root: Path) -> str:
    """Resolve a source name. If name is None, auto-pick when exactly one source exists.

    Raises:
        AmbiguousSource: if name is None and out_root contains >1 source.
        NoSourceFound: if out_root contains 0 sources, or name is given but absent.
    """
    available = list_sources(out_root)
    if name is None:
        if len(available) == 0:
            raise NoSourceFound(f"No conversations found in {out_root}")
        if len(available) > 1:
            raise AmbiguousSource(
                f"Multiple conversations available: {available}. Specify --source."
            )
        return available[0]
    if name not in available:
        raise NoSourceFound(f"Source {name!r} not found in {out_root}. Available: {available}")
    return name

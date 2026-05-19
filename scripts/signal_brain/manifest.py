"""Manifest tracking incremental ingest state."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


SCHEMA_VERSION = 1


@dataclass
class Manifest:
    last_processed_msg_ts: str | None = None
    burst_count: int = 0
    burst_threshold_min: int = 60
    content_hashes: dict[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def load_or_init(cls, path: Path, burst_threshold_min: int) -> "Manifest":
        path = Path(path)
        if not path.exists():
            return cls(burst_threshold_min=burst_threshold_min)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt file — start fresh.
            return cls(burst_threshold_min=burst_threshold_min)
        if data.get("schema_version") != SCHEMA_VERSION:
            # Schema mismatch — start fresh (caller can detect by checking content_hashes is empty).
            return cls(burst_threshold_min=burst_threshold_min)
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def save(self, path: Path) -> None:
        Path(path).write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

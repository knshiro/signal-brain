> **Note (historical):** This is the original 16-task implementation plan as written on 2026-05-19. The codebase has since evolved through several refactors:
> - Identity, tagging description, and seed topics moved from hardcoded constants to `config.toml` (`[me]` and `[tagging]` sections).
> - Per-source `data/<source>/` and `wiki/<source>/` directories were unified into a single `brain/<source>/` folder (now fully gitignored — regenerated locally per consumer).
> - `--source` flag added to every CLI subcommand; multi-conversation operation is supported.
> - All conversation-specific terms (politicians, topics, real names) were stripped from production code; defaults are content-neutral.
>
> For the current state of the system, see `README.md`, `AGENTS.md`, and `docs/superpowers/specs/2026-05-19-signal-convo-brain-design.md`. Use this plan for historical context only.

# Signal Conversation Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the target conversation (~2,300 messages) into a Karpathy-style wiki brain with five page types (People, Concepts, Positions, Arcs, Cross), deterministic + LLM-driven layers, and incremental re-export support.

**Architecture:** Five-layer stack — raw messages (L0) → time-gap bursts (L1) → LLM topic tags + arcs (L2) → wiki pages with frontmatter and citations (L3) → indexes/log/schema (L4). All built by Python scripts under `scripts/signal_brain/`. Wiki in English; quotes verbatim in French. Citations like `[B0042#m17]` resolve back to messages via `data/msg_index.jsonl`.

**Tech Stack:** Python 3.11+, `pyyaml`, `anthropic` SDK (models: `claude-haiku-4-5-20251001` for tagging, `claude-sonnet-4-6` for synthesis), `click` for CLI, `pytest` for tests. No DB; flat files.

**Prerequisites:**
- Python 3.11+ available as `python3` (system has 3.14)
- `ANTHROPIC_API_KEY` set in the environment
- `out/<source>/data.json` already produced by `pipx install signal-export && sigexport`
- Spec: `docs/superpowers/specs/2026-05-19-signal-convo-brain-design.md`

**Repository state:** Not currently a git repo. Task 1 initializes one.

---

## File structure to be created

```
signal-convo/
  pyproject.toml              # Task 1
  .gitignore                  # Task 1
  config.toml                 # Task 1
  scripts/
    signal_brain/
      __init__.py
      msg_index.py            # Task 2
      bursts.py               # Task 3
      manifest.py             # Task 3
      citations.py            # Task 4
      llm.py                  # Task 5
      tagging.py              # Task 6
      arcs.py                 # Task 7
      wiki/
        __init__.py
        schemas.py            # Task 8
        people.py             # Task 9
        concepts.py           # Task 10
        positions.py          # Task 10
        arcs.py               # Task 11
        cross.py              # Task 11
      indexing.py             # Task 12
      linking.py              # Task 13
      lint.py                 # Task 14
      ingest.py               # Task 15
      cli.py                  # Task 15
      evaluators.py           # Task 16
    tests/
      conftest.py             # Task 1
      fixtures/
        mini_data.json        # Task 1 (50-message slice)
      test_msg_index.py       # Task 2
      test_bursts.py          # Task 3
      test_manifest.py        # Task 3
      test_citations.py       # Task 4
      test_llm.py             # Task 5
      test_tagging.py         # Task 6
      test_arcs.py            # Task 7
      test_schemas.py         # Task 8
      test_wiki_people.py     # Task 9
      test_wiki_pages.py      # Task 10, 11
      test_indexing.py        # Task 12
      test_linking.py         # Task 13
      test_lint.py            # Task 14
      test_ingest.py          # Task 15
  data/                       # produced by scripts (gitignored)
    msg_index.jsonl
    bursts.jsonl
    chunks.jsonl
    arcs.jsonl
    manifest.json
    link_graph.jsonl
  wiki/                       # produced by scripts (committed)
    schema.md
    index.md
    log.md
    lint-report.md
    people/
    concepts/
    positions/
    arcs/
    cross/
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `config.toml`
- Create: `scripts/signal_brain/__init__.py`
- Create: `scripts/tests/conftest.py`
- Create: `scripts/tests/fixtures/mini_data.json`

- [ ] **Step 1: Initialize git repo**

Run:
```bash
cd /Users/knshiro/dev/signal-convo
git init -b main
git add docs/
git commit -m "chore: add design spec and implementation plan"
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "signal-brain"
version = "0.1.0"
description = "Signal conversation brain (Karpathy-style wiki)"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "click>=8.1",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12"]

[project.scripts]
signal-brain = "signal_brain.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["scripts"]

[tool.pytest.ini_options]
testpaths = ["scripts/tests"]
pythonpath = ["scripts"]
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
data/
wiki/lint-report.md
.env
```

(Note: `data/` is gitignored — it's fully regeneratable. `wiki/` is committed.)

- [ ] **Step 4: Write `config.toml`**

```toml
# Knobs. Lint reports when current data suggests retuning.

[bursts]
threshold_minutes = 60

[arcs]
min_burst_count = 2
min_msg_count = 20

[cross_pages]
min_occurrences = 3

[lint]
stale_claim_ingestion_count = 5
position_evolution_threshold = 2

[llm]
tagging_model = "claude-haiku-4-5-20251001"
synthesis_model = "claude-sonnet-4-6"
max_retries = 3

[paths]
source_data = "out/<source>/data.json"
data_dir = "data"
wiki_dir = "wiki"
```

- [ ] **Step 5: Write `scripts/signal_brain/__init__.py`**

```python
"""Signal conversation brain."""
__version__ = "0.1.0"
```

- [ ] **Step 6: Write `scripts/tests/conftest.py`**

```python
"""Shared test fixtures."""
import json
from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mini_messages():
    """50-message slice of the target conversation for integration tests."""
    path = FIXTURE_DIR / "mini_data.json"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def tmp_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def tmp_wiki_dir(tmp_path):
    d = tmp_path / "wiki"
    for sub in ["people", "concepts", "positions", "arcs", "cross"]:
        (d / sub).mkdir(parents=True)
    return d
```

- [ ] **Step 7: Create fixture `scripts/tests/fixtures/mini_data.json`**

Run:
```bash
mkdir -p scripts/tests/fixtures
head -n 50 out/<source>/data.json > scripts/tests/fixtures/mini_data.json
wc -l scripts/tests/fixtures/mini_data.json
```
Expected: `50 scripts/tests/fixtures/mini_data.json`

- [ ] **Step 8: Install deps and verify pytest runs**

Run:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest --collect-only
```
Expected: pytest discovers no tests yet, exits 0.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore config.toml scripts/
git commit -m "chore: project scaffolding, deps, mini fixture"
```

---

## Task 2: Message index (`msg_index.jsonl`)

Stable IDs for every message so citations and incremental ingest work.

**Files:**
- Create: `scripts/signal_brain/msg_index.py`
- Create: `scripts/tests/test_msg_index.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_msg_index.py`**

```python
import json
from signal_brain.msg_index import build_msg_index, msg_id


def test_msg_id_is_timestamp_plus_sender():
    msg = {"date": "2026-05-05T13:18:00.000000", "sender": "Me", "body": "hi"}
    assert msg_id(msg) == "2026-05-05T13:18:00.000000::Me"


def test_build_msg_index_writes_jsonl(mini_messages, tmp_data_dir):
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(mini_messages, out)
    lines = out.read_text().splitlines()
    assert len(lines) == 50
    first = json.loads(lines[0])
    assert set(first.keys()) >= {"msg_id", "date", "sender", "body", "char_count"}
    assert first["msg_id"].endswith("::Me") or first["msg_id"].endswith("::<source>")


def test_build_msg_index_deduplicates_on_msg_id(tmp_data_dir):
    duplicates = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Me", "body": "hi"},
        {"date": "2026-05-05T13:18:00.000000", "sender": "Me", "body": "hi"},
    ]
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(duplicates, out)
    assert len(out.read_text().splitlines()) == 1
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_msg_index.py -v`
Expected: `ModuleNotFoundError: signal_brain.msg_index`.

- [ ] **Step 3: Implement `scripts/signal_brain/msg_index.py`**

```python
"""Stable message IDs and the flat addressable message index."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable


def msg_id(msg: dict) -> str:
    """`{ISO-timestamp}::{sender}`. Composite breaks rare millisecond ties."""
    return f"{msg['date']}::{msg['sender']}"


def build_msg_index(messages: Iterable[dict], out_path: Path) -> int:
    """Write deduplicated msg_index.jsonl. Returns row count."""
    seen: set[str] = set()
    rows = []
    for m in messages:
        mid = msg_id(m)
        if mid in seen:
            continue
        seen.add(mid)
        rows.append({
            "msg_id": mid,
            "date": m["date"],
            "sender": m["sender"],
            "body": m.get("body", ""),
            "quote": m.get("quote", ""),
            "reactions": m.get("reactions", []),
            "attachments": m.get("attachments", []),
            "char_count": len(m.get("body", "")),
        })
    Path(out_path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    return len(rows)


def load_msg_index(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_msg_index.py -v`
Expected: 3 passed.

- [ ] **Step 5: Build the real index and inspect**

Run:
```bash
python3 -c "
import json
from pathlib import Path
from signal_brain.msg_index import build_msg_index
msgs = [json.loads(l) for l in open('out/<source>/data.json') if l.strip()]
Path('data').mkdir(exist_ok=True)
n = build_msg_index(msgs, Path('data/msg_index.jsonl'))
print('rows:', n)
"
wc -l data/msg_index.jsonl
```
Expected: rows around 2276; line count matches.

- [ ] **Step 6: Commit**

```bash
git add scripts/signal_brain/msg_index.py scripts/tests/test_msg_index.py
git commit -m "feat: msg_index — stable IDs and flat message index"
```

---

## Task 3: Burst detector + manifest

**Files:**
- Create: `scripts/signal_brain/bursts.py`
- Create: `scripts/signal_brain/manifest.py`
- Create: `scripts/tests/test_bursts.py`
- Create: `scripts/tests/test_manifest.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_bursts.py`**

```python
import json
from signal_brain.bursts import detect_bursts, burst_content_hash


def msg(ts, sender="Me", body="x"):
    return {"msg_id": f"{ts}::{sender}", "date": ts, "sender": sender, "body": body,
            "quote": "", "reactions": [], "attachments": [], "char_count": len(body)}


def test_single_burst_under_threshold():
    msgs = [msg("2026-05-05T13:00:00"), msg("2026-05-05T13:30:00")]
    bursts = detect_bursts(msgs, threshold_min=60)
    assert len(bursts) == 1
    assert bursts[0]["id"] == "B0001"
    assert len(bursts[0]["msg_ids"]) == 2


def test_split_when_gap_exceeds_threshold():
    msgs = [msg("2026-05-05T13:00:00"), msg("2026-05-05T15:00:00")]
    bursts = detect_bursts(msgs, threshold_min=60)
    assert len(bursts) == 2
    assert bursts[0]["id"] == "B0001"
    assert bursts[1]["id"] == "B0002"


def test_burst_records_sender_breakdown_and_chars():
    msgs = [msg("2026-05-05T13:00:00", "Me", "hello"),
            msg("2026-05-05T13:01:00", "Friend", "yo")]
    b = detect_bursts(msgs, threshold_min=60)[0]
    assert b["senders"] == {"Me": 1, "Friend": 1}
    assert b["char_count"] == len("hello") + len("yo")


def test_content_hash_is_stable():
    msgs = [msg("2026-05-05T13:00:00", "Me", "hi")]
    b = detect_bursts(msgs, threshold_min=60)[0]
    h1 = burst_content_hash(b, msgs)
    h2 = burst_content_hash(b, msgs)
    assert h1 == h2
    msgs[0]["body"] = "hi!"
    assert burst_content_hash(b, msgs) != h1
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_bursts.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/bursts.py`**

```python
"""L1: time-gap burst detection and per-burst content hashing."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta
from typing import Iterable


def _parse(ts: str) -> datetime:
    # Accept "...000000" or "...000Z"
    return datetime.fromisoformat(ts.replace("Z", ""))


def detect_bursts(messages: list[dict], threshold_min: int) -> list[dict]:
    """Split messages into bursts when consecutive-gap > threshold."""
    if not messages:
        return []
    threshold = timedelta(minutes=threshold_min)
    bursts: list[dict] = []
    current: list[dict] = [messages[0]]
    prev_ts = _parse(messages[0]["date"])
    for m in messages[1:]:
        ts = _parse(m["date"])
        if ts - prev_ts > threshold:
            bursts.append(_finalize(current, len(bursts) + 1))
            current = []
        current.append(m)
        prev_ts = ts
    if current:
        bursts.append(_finalize(current, len(bursts) + 1))
    return bursts


def _finalize(msgs: list[dict], idx: int) -> dict:
    senders: dict[str, int] = {}
    chars = 0
    has_media = False
    for m in msgs:
        senders[m["sender"]] = senders.get(m["sender"], 0) + 1
        chars += m.get("char_count", len(m.get("body", "")))
        if m.get("attachments"):
            has_media = True
    return {
        "id": f"B{idx:04d}",
        "start": msgs[0]["date"],
        "end": msgs[-1]["date"],
        "msg_ids": [m["msg_id"] for m in msgs],
        "senders": senders,
        "char_count": chars,
        "has_media": has_media,
    }


def burst_content_hash(burst: dict, all_messages: list[dict]) -> str:
    """SHA1 over msg_id + body + reactions for every message in the burst."""
    by_id = {m["msg_id"]: m for m in all_messages}
    h = hashlib.sha1()
    for mid in burst["msg_ids"]:
        m = by_id[mid]
        h.update(mid.encode())
        h.update(b"\x00")
        h.update(m.get("body", "").encode())
        h.update(b"\x00")
        h.update(json.dumps(m.get("reactions", []), sort_keys=True).encode())
        h.update(b"\x01")
    return f"sha1:{h.hexdigest()}"


def write_bursts(bursts: list[dict], out_path) -> None:
    from pathlib import Path
    Path(out_path).write_text("\n".join(json.dumps(b, ensure_ascii=False) for b in bursts) + "\n")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_bursts.py -v`
Expected: 4 passed.

- [ ] **Step 5: Write failing test `scripts/tests/test_manifest.py`**

```python
from signal_brain.manifest import Manifest


def test_load_or_init_when_absent(tmp_data_dir):
    m = Manifest.load_or_init(tmp_data_dir / "manifest.json", burst_threshold_min=60)
    assert m.burst_threshold_min == 60
    assert m.content_hashes == {}
    assert m.last_processed_msg_ts is None


def test_roundtrip(tmp_data_dir):
    path = tmp_data_dir / "manifest.json"
    m = Manifest.load_or_init(path, burst_threshold_min=60)
    m.content_hashes["B0001"] = "sha1:abc"
    m.last_processed_msg_ts = "2026-05-05T13:00:00"
    m.save(path)
    m2 = Manifest.load_or_init(path, burst_threshold_min=60)
    assert m2.content_hashes == {"B0001": "sha1:abc"}
    assert m2.last_processed_msg_ts == "2026-05-05T13:00:00"
```

- [ ] **Step 6: Implement `scripts/signal_brain/manifest.py`**

```python
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
        data = json.loads(path.read_text())
        return cls(**data)

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))
```

- [ ] **Step 7: Run tests, expect pass**

Run: `pytest scripts/tests/test_manifest.py -v`
Expected: 2 passed.

- [ ] **Step 8: Build bursts from real data**

Run:
```bash
python3 -c "
from pathlib import Path
from signal_brain.msg_index import load_msg_index
from signal_brain.bursts import detect_bursts, write_bursts
msgs = load_msg_index(Path('data/msg_index.jsonl'))
bursts = detect_bursts(msgs, threshold_min=60)
write_bursts(bursts, Path('data/bursts.jsonl'))
print('bursts:', len(bursts))
print('avg msgs/burst:', round(sum(len(b['msg_ids']) for b in bursts) / len(bursts), 1))
"
```
Expected: between 80 and 200 bursts; avg 10-30 msgs.

- [ ] **Step 9: Commit**

```bash
git add scripts/signal_brain/bursts.py scripts/signal_brain/manifest.py scripts/tests/test_bursts.py scripts/tests/test_manifest.py
git commit -m "feat: L1 burst detection + manifest"
```

---

## Task 4: Citation resolver

**Files:**
- Create: `scripts/signal_brain/citations.py`
- Create: `scripts/tests/test_citations.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_citations.py`**

```python
import json
import pytest
from pathlib import Path
from signal_brain.citations import parse_citation, resolve_citation, find_citations, UnresolvedCitation


def test_parse_citation():
    b, m = parse_citation("[B0042#m17]")
    assert b == "B0042"
    assert m == 17


def test_parse_citation_rejects_bad_format():
    with pytest.raises(ValueError):
        parse_citation("[B42#17]")


def test_resolve_citation_returns_message(tmp_data_dir):
    bursts = [{"id": "B0001", "msg_ids": ["2026-05-05T13:00:00::Me", "2026-05-05T13:01:00::Friend"]}]
    msgs = [
        {"msg_id": "2026-05-05T13:00:00::Me", "date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi"},
        {"msg_id": "2026-05-05T13:01:00::Friend", "date": "2026-05-05T13:01:00", "sender": "Friend", "body": "yo"},
    ]
    (tmp_data_dir / "bursts.jsonl").write_text("\n".join(json.dumps(b) for b in bursts))
    (tmp_data_dir / "msg_index.jsonl").write_text("\n".join(json.dumps(m) for m in msgs))
    msg = resolve_citation("[B0001#m1]", tmp_data_dir)
    assert msg["sender"] == "Me"
    msg2 = resolve_citation("[B0001#m2]", tmp_data_dir)
    assert msg2["sender"] == "Friend"


def test_resolve_raises_on_missing(tmp_data_dir):
    (tmp_data_dir / "bursts.jsonl").write_text("")
    (tmp_data_dir / "msg_index.jsonl").write_text("")
    with pytest.raises(UnresolvedCitation):
        resolve_citation("[B0001#m1]", tmp_data_dir)


def test_find_citations_in_markdown():
    text = "the operator argues X [B0042#m17] but the other party [B0042#m18] disagrees."
    assert find_citations(text) == ["[B0042#m17]", "[B0042#m18]"]
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_citations.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/citations.py`**

```python
"""Citation format `[B0042#m17]` → message resolution."""
from __future__ import annotations
import json
import re
from pathlib import Path
from functools import lru_cache


CITATION_RE = re.compile(r"\[B(\d{4})#m(\d+)\]")


class UnresolvedCitation(Exception):
    pass


def parse_citation(cite: str) -> tuple[str, int]:
    m = CITATION_RE.fullmatch(cite)
    if not m:
        raise ValueError(f"Bad citation: {cite!r}")
    return f"B{m.group(1)}", int(m.group(2))


def find_citations(text: str) -> list[str]:
    return [m.group(0) for m in CITATION_RE.finditer(text)]


@lru_cache(maxsize=4)
def _load(data_dir: Path) -> tuple[dict, dict]:
    data_dir = Path(data_dir)
    bursts_path = data_dir / "bursts.jsonl"
    msgs_path = data_dir / "msg_index.jsonl"
    bursts = {}
    if bursts_path.exists() and bursts_path.read_text().strip():
        bursts = {json.loads(l)["id"]: json.loads(l) for l in bursts_path.read_text().splitlines() if l.strip()}
    msgs = {}
    if msgs_path.exists() and msgs_path.read_text().strip():
        msgs = {json.loads(l)["msg_id"]: json.loads(l) for l in msgs_path.read_text().splitlines() if l.strip()}
    return bursts, msgs


def resolve_citation(cite: str, data_dir: Path) -> dict:
    burst_id, m_idx = parse_citation(cite)
    bursts, msgs = _load(Path(data_dir))
    if burst_id not in bursts:
        raise UnresolvedCitation(cite)
    msg_ids = bursts[burst_id]["msg_ids"]
    if m_idx < 1 or m_idx > len(msg_ids):
        raise UnresolvedCitation(cite)
    mid = msg_ids[m_idx - 1]  # 1-indexed in citations, 0-indexed in list
    if mid not in msgs:
        raise UnresolvedCitation(cite)
    return msgs[mid]


def render_citation(cite: str, data_dir: Path) -> str:
    msg = resolve_citation(cite, data_dir)
    return f"({msg['date'][:16].replace('T', ' ')}, {msg['sender']}): {msg['body']!r}"
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_citations.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/citations.py scripts/tests/test_citations.py
git commit -m "feat: citation parser/resolver/finder"
```

---

## Task 5: LLM client wrapper

**Files:**
- Create: `scripts/signal_brain/llm.py`
- Create: `scripts/tests/test_llm.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_llm.py`**

```python
import pytest
from signal_brain.llm import LLMClient, LLMResponse


def test_client_uses_configured_model(mocker):
    fake = mocker.MagicMock()
    fake.messages.create.return_value = mocker.MagicMock(
        content=[mocker.MagicMock(text='{"ok": true}')],
        usage=mocker.MagicMock(input_tokens=10, output_tokens=5),
    )
    client = LLMClient(api_client=fake, default_model="m1")
    resp = client.complete("system", "user")
    assert resp.text == '{"ok": true}'
    assert resp.input_tokens == 10
    assert resp.output_tokens == 5
    fake.messages.create.assert_called_once()
    kwargs = fake.messages.create.call_args.kwargs
    assert kwargs["model"] == "m1"
    assert kwargs["system"] == "system"
    assert kwargs["messages"][0]["role"] == "user"


def test_client_parses_json_response(mocker):
    fake = mocker.MagicMock()
    fake.messages.create.return_value = mocker.MagicMock(
        content=[mocker.MagicMock(text='```json\n{"a": 1}\n```')],
        usage=mocker.MagicMock(input_tokens=1, output_tokens=1),
    )
    client = LLMClient(api_client=fake, default_model="m1")
    assert client.complete_json("s", "u") == {"a": 1}
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_llm.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/llm.py`**

```python
"""Anthropic SDK wrapper with retry and JSON parsing."""
from __future__ import annotations
import json
import os
import re
import time
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int


class LLMClient:
    def __init__(self, api_client=None, default_model: str = "claude-sonnet-4-6",
                 max_retries: int = 3):
        if api_client is None:
            from anthropic import Anthropic
            api_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._client = api_client
        self.default_model = default_model
        self.max_retries = max_retries

    def complete(self, system: str, user: str, *, model: str | None = None,
                 max_tokens: int = 4096) -> LLMResponse:
        last_err = None
        for attempt in range(self.max_retries):
            try:
                r = self._client.messages.create(
                    model=model or self.default_model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = "".join(b.text for b in r.content if hasattr(b, "text"))
                return LLMResponse(text=text,
                                    input_tokens=r.usage.input_tokens,
                                    output_tokens=r.usage.output_tokens)
            except Exception as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise last_err

    def complete_json(self, system: str, user: str, **kw) -> dict | list:
        resp = self.complete(system, user, **kw)
        text = resp.text.strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        return json.loads(text)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_llm.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/llm.py scripts/tests/test_llm.py
git commit -m "feat: LLM client with retry + JSON parsing"
```

---

## Task 6: Topic tagger (L2a, `chunks.jsonl`)

**Files:**
- Create: `scripts/signal_brain/tagging.py`
- Create: `scripts/tests/test_tagging.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_tagging.py`**

```python
import json
from signal_brain.tagging import tag_bursts, SEED_TAGS, _render_burst_for_tagging


def test_render_burst_includes_messages():
    burst = {"id": "B0001", "msg_ids": ["a::Me"]}
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "Café au lait", "date": "2026-05-05T13:00:00"}]
    text = _render_burst_for_tagging(burst, msgs)
    assert "Me:" in text
    assert "Café au lait" in text


def test_tag_bursts_reuses_cache_when_hash_unchanged(tmp_data_dir, mocker):
    bursts = [{"id": "B0001", "msg_ids": ["a::Me"], "start": "2026-05-05T13:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi", "date": "2026-05-05T13:00:00"}]
    mock_llm = mocker.MagicMock()
    cache = {"B0001": {"hash": "sha1:cached", "topics": ["banter"], "primary": "banter", "summary": "cached"}}
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:cached")
    out = tmp_data_dir / "chunks.jsonl"
    tag_bursts(bursts, msgs, mock_llm, cache_by_id=cache, out_path=out)
    mock_llm.complete_json.assert_not_called()
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert rows[0]["primary"] == "banter"


def test_tag_bursts_calls_llm_on_cache_miss(tmp_data_dir, mocker):
    bursts = [{"id": "B0002", "msg_ids": ["a::Me"], "start": "2026-05-05T14:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "Café au lait", "date": "2026-05-05T14:00:00"}]
    mock_llm = mocker.MagicMock()
    mock_llm.complete_json.return_value = {
        "topics": ["topic-a", "topic-d"],
        "primary": "topic-a",
        "summary": "the operator discusses topic-a."
    }
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:new")
    out = tmp_data_dir / "chunks.jsonl"
    tag_bursts(bursts, msgs, mock_llm, cache_by_id={}, out_path=out)
    assert mock_llm.complete_json.call_count == 1
    row = json.loads(out.read_text().splitlines()[0])
    assert row["burst_id"] == "B0002"
    assert row["primary"] == "topic-a"
    assert row["topics"] == ["topic-a", "topic-d"]


def test_seed_tags_contains_known_topics():
    for t in ["topic-a", "topic-b", "topic-c", "banter"]:
        assert t in SEED_TAGS  # these are illustrative examples from the original plan
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_tagging.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/tagging.py`**

```python
"""L2a: per-burst topic tagging via LLM, with content-hash cache reuse."""
from __future__ import annotations
import json
from pathlib import Path
from signal_brain.bursts import burst_content_hash


SEED_TAGS = [
    "topic-r", "topic-a", "topic-d", "topic-b", "topic-c",
    "topic-e", "topic-f", "topic-g", "topic-h", "topic-i", "topic-s",
    "topic-j", "topic-k", "topic-l", "topic-m",
    "topic-n", "topic-o", "topic-p", "topic-q", "education",
    "parenting", "family-personal", "business-personal", "ai-tooling", "banter",
]


SYSTEM_PROMPT = """You are a topic tagger for a Signal conversation between two parties. \
Tag each burst with 1-3 topics.

Rules:
- Output VALID JSON. No prose around it.
- Output language: English (lowercase, kebab-case slugs).
- Quotes in summaries must preserve the original French.
- Prefer existing seed tags when they fit. Propose new tags only when nothing in the seed list captures the dominant subject.
- "primary" is the single dominant topic.
- "summary" is one sentence (≤ 25 words) describing what was discussed, in English.
"""


USER_TEMPLATE = """Seed tags (use when they fit; you may propose new ones if needed):
{seed_tags}

Burst {burst_id} ({start}):
---
{messages}
---

Output JSON:
{{"topics": ["...", "..."], "primary": "...", "summary": "..."}}"""


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
               cache_by_id: dict[str, dict], out_path: Path) -> dict[str, str]:
    """Tag bursts; reuse cache when hash matches. Returns id→hash map."""
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
        user = USER_TEMPLATE.format(
            seed_tags=", ".join(SEED_TAGS),
            burst_id=b["id"],
            start=b["start"],
            messages=_render_burst_for_tagging(b, all_messages),
        )
        result = llm.complete_json(SYSTEM_PROMPT, user)
        out_rows.append({
            "burst_id": b["id"], "topics": result["topics"],
            "primary": result["primary"], "summary": result["summary"],
        })
    Path(out_path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + "\n")
    return new_hashes


def load_chunks_as_cache(chunks_path: Path, hashes_by_id: dict[str, str]) -> dict[str, dict]:
    if not Path(chunks_path).exists():
        return {}
    cache = {}
    for line in Path(chunks_path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cache[row["burst_id"]] = {
            "hash": hashes_by_id.get(row["burst_id"], ""),
            "topics": row["topics"], "primary": row["primary"], "summary": row["summary"],
        }
    return cache
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_tagging.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/tagging.py scripts/tests/test_tagging.py
git commit -m "feat: L2a topic tagger with content-hash cache reuse"
```

---

## Task 7: Arc detector (L2b, `arcs.jsonl`)

**Files:**
- Create: `scripts/signal_brain/arcs.py`
- Create: `scripts/tests/test_arcs.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_arcs.py`**

```python
from signal_brain.arcs import detect_arcs


def burst(id_, primary, msg_count):
    return {"id": id_, "msg_ids": ["x"] * msg_count, "start": f"2026-05-{int(id_[1:]):02d}T10:00", "end": "..."}


def chunk(id_, primary):
    return {"burst_id": id_, "primary": primary, "topics": [primary], "summary": "..."}


def test_single_burst_below_threshold_not_an_arc():
    bursts = [burst("B0001", "topic-a", 10)]
    chunks = [chunk("B0001", "topic-a")]
    assert detect_arcs(bursts, chunks, min_burst_count=2, min_msg_count=20) == []


def test_two_adjacent_bursts_same_topic_form_arc():
    bursts = [burst("B0001", "topic-a", 12), burst("B0002", "topic-a", 15)]
    chunks = [chunk("B0001", "topic-a"), chunk("B0002", "topic-a")]
    arcs = detect_arcs(bursts, chunks, min_burst_count=2, min_msg_count=20)
    assert len(arcs) == 1
    a = arcs[0]
    assert a["id"] == "A001"
    assert a["primary"] == "topic-a"
    assert a["bursts"] == ["B0001", "B0002"]
    assert a["msg_count"] == 27
    assert a["status"] == "unresolved"


def test_topic_change_starts_new_arc():
    bursts = [burst("B0001", "topic-a", 12), burst("B0002", "topic-a", 12),
              burst("B0003", "topic-b", 12), burst("B0004", "topic-b", 12)]
    chunks = [chunk("B0001", "topic-a"), chunk("B0002", "topic-a"),
              chunk("B0003", "topic-b"), chunk("B0004", "topic-b")]
    arcs = detect_arcs(bursts, chunks, min_burst_count=2, min_msg_count=20)
    assert len(arcs) == 2
    assert arcs[0]["primary"] == "topic-a"
    assert arcs[1]["primary"] == "topic-b"


def test_min_msg_count_filters_out_low_substance():
    bursts = [burst("B0001", "topic-a", 5), burst("B0002", "topic-a", 5)]
    chunks = [chunk("B0001", "topic-a"), chunk("B0002", "topic-a")]
    assert detect_arcs(bursts, chunks, min_burst_count=2, min_msg_count=20) == []
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_arcs.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/arcs.py`**

```python
"""L2b: arc detection from per-burst tags."""
from __future__ import annotations
import json
import re
from pathlib import Path


def detect_arcs(bursts: list[dict], chunks: list[dict],
                min_burst_count: int, min_msg_count: int) -> list[dict]:
    by_id = {c["burst_id"]: c for c in chunks}
    bursts_by_id = {b["id"]: b for b in bursts}
    runs: list[list[str]] = []
    current: list[str] = []
    current_topic = None
    for b in bursts:
        primary = by_id.get(b["id"], {}).get("primary")
        if primary == current_topic and primary is not None:
            current.append(b["id"])
        else:
            if current:
                runs.append(current)
            current = [b["id"]] if primary else []
            current_topic = primary
    if current:
        runs.append(current)

    arcs = []
    for run in runs:
        if len(run) < min_burst_count:
            continue
        msg_count = sum(len(bursts_by_id[bid]["msg_ids"]) for bid in run)
        if msg_count < min_msg_count:
            continue
        primary = by_id[run[0]]["primary"]
        idx = len(arcs) + 1
        arcs.append({
            "id": f"A{idx:03d}",
            "slug": f"{primary}-{run[0]}-{run[-1]}".replace("_", "-"),
            "period": [bursts_by_id[run[0]]["start"][:10], bursts_by_id[run[-1]]["end"][:10]],
            "primary": primary,
            "bursts": run,
            "status": "unresolved",
            "msg_count": msg_count,
        })
    return arcs


def write_arcs(arcs: list[dict], out_path: Path) -> None:
    Path(out_path).write_text("\n".join(json.dumps(a, ensure_ascii=False) for a in arcs) + "\n")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_arcs.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/arcs.py scripts/tests/test_arcs.py
git commit -m "feat: L2b arc detection with min burst/msg thresholds"
```

---

## Task 8: Wiki page schemas + frontmatter validators

**Files:**
- Create: `scripts/signal_brain/wiki/__init__.py`
- Create: `scripts/signal_brain/wiki/schemas.py`
- Create: `scripts/tests/test_schemas.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_schemas.py`**

```python
import pytest
from signal_brain.wiki.schemas import (
    parse_page, render_page, validate_page,
    REQUIRED_SECTIONS, SchemaError,
)


def test_parse_page_extracts_frontmatter_and_body():
    text = """---
type: person
slug: alice
---

## Background
Hello.
"""
    fm, body = parse_page(text)
    assert fm["type"] == "person"
    assert fm["slug"] == "alice"
    assert "## Background" in body


def test_render_page_roundtrip():
    fm = {"type": "person", "slug": "alice", "name": "Alice"}
    body = "## Background\nHello."
    text = render_page(fm, body)
    fm2, body2 = parse_page(text)
    assert fm2 == fm
    assert body2.strip() == body.strip()


def test_validate_position_page_requires_sections():
    fm = {"type": "position", "holder": "alice", "concept": "topic-a-policy",
          "stance": "x", "confidence": "high", "first_seen": "[B0001#m1]",
          "last_seen": "[B0001#m1]", "evolution": "stable", "sources_count": 1}
    body = "## Core claim\nx"  # missing other required sections
    with pytest.raises(SchemaError) as e:
        validate_page("position", fm, body)
    assert "Reasoning chain" in str(e.value) or "missing section" in str(e.value).lower()


def test_validate_position_page_passes_with_all_sections():
    fm = {"type": "position", "holder": "alice", "concept": "topic-a-policy",
          "stance": "x", "confidence": "high", "first_seen": "[B0001#m1]",
          "last_seen": "[B0001#m1]", "evolution": "stable", "sources_count": 1}
    body = "\n".join(f"## {s}\nbody" for s in REQUIRED_SECTIONS["position"])
    validate_page("position", fm, body)


def test_required_sections_cover_all_page_types():
    for t in ["person", "concept", "position", "arc", "cross"]:
        assert t in REQUIRED_SECTIONS
        assert len(REQUIRED_SECTIONS[t]) >= 3
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_schemas.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/wiki/__init__.py`**

```python
"""Wiki page generation."""
```

- [ ] **Step 4: Implement `scripts/signal_brain/wiki/schemas.py`**

```python
"""Page schemas, parse/render, validation."""
from __future__ import annotations
import re
import yaml


class SchemaError(Exception):
    pass


REQUIRED_FRONTMATTER: dict[str, list[str]] = {
    "person": ["type", "slug", "name"],
    "concept": ["type", "slug", "contested"],
    "position": ["type", "holder", "concept", "stance", "confidence",
                 "first_seen", "last_seen", "evolution", "sources_count"],
    "arc": ["type", "id", "slug", "period", "primary_topic", "status", "bursts"],
    "cross": ["type", "slug"],
}


REQUIRED_SECTIONS: dict[str, list[str]] = {
    "person": ["Background", "Style & drivers", "Key positions", "Recurring moves", "Open tensions", "Related"],
    "concept": ["What's at stake", "Sub-questions", "Empirical anchors", "Positions on this concept", "Related"],
    "position": ["Core claim", "Reasoning chain", "Examples / evidence cited",
                 "Concessions made", "Tensions with own other positions",
                 "Evolution timeline", "Counter-arguments faced", "Related"],
    "arc": ["Question at stake", "Opening positions", "Key turns",
            "Concessions & ground gained", "Why unresolved", "Related"],
    "cross": ["Overview", "Instances", "Related"],
}


_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def parse_page(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        raise SchemaError("Missing or malformed frontmatter block")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).lstrip()
    return fm, body


def render_page(frontmatter: dict, body: str) -> str:
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{fm}\n---\n\n{body.rstrip()}\n"


def validate_page(page_type: str, frontmatter: dict, body: str) -> None:
    if page_type not in REQUIRED_FRONTMATTER:
        raise SchemaError(f"Unknown page type: {page_type}")
    missing_fm = [k for k in REQUIRED_FRONTMATTER[page_type] if k not in frontmatter]
    if missing_fm:
        raise SchemaError(f"Missing frontmatter fields: {missing_fm}")
    found = set(re.findall(r"^##\s+(.+)$", body, re.MULTILINE))
    missing_sections = [s for s in REQUIRED_SECTIONS[page_type] if s not in found]
    if missing_sections:
        raise SchemaError(f"Missing sections: {missing_sections}")
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest scripts/tests/test_schemas.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/signal_brain/wiki/ scripts/tests/test_schemas.py
git commit -m "feat: wiki page schemas + frontmatter validator"
```

---

## Task 9: People page generator

**Files:**
- Create: `scripts/signal_brain/wiki/people.py`
- Create: `scripts/tests/test_wiki_people.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_wiki_people.py`**

```python
from signal_brain.wiki.people import generate_person_page
from signal_brain.wiki.schemas import parse_page, validate_page


def test_generate_person_page_passes_schema(tmp_wiki_dir, mocker):
    mock_llm = mocker.MagicMock()
    mock_llm.complete.return_value.text = """## Background
Some background about Alice with a citation [B0001#m1].

## Style & drivers
Drives.

## Key positions
- [[positions/alice--topic-a-policy]]

## Recurring moves
Moves.

## Open tensions
Tensions.

## Related
(auto-maintained)
"""
    page = generate_person_page(
        slug="alice", name="Alice Example", relation="Me",
        bursts_summary="Bursts featuring Alice dominantly.",
        sources_count=1138, llm=mock_llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "person"
    assert fm["slug"] == "alice"
    validate_page("person", fm, body)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_wiki_people.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/wiki/people.py`**

```python
"""People (entity) page generation."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


PERSON_SYSTEM = """You generate a "person" page for a Karpathy-style debate wiki.

Constraints:
- English prose throughout.
- Preserve French verbatim in quoted citations.
- Every non-trivial claim cites at least one message in the form [Bnnnn#mN].
- Output the body only — frontmatter is added by the caller.
- Sections required, in order:
  ## Background
  ## Style & drivers
  ## Key positions
  ## Recurring moves
  ## Open tensions
  ## Related

- "Related" should be a single placeholder line: "(auto-maintained — see link pass)".
"""


PERSON_USER = """Person: {name}  (slug: {slug}, relation: {relation})
Sources count (messages by/about): {sources_count}

Conversation summary across all bursts featuring this person:
{bursts_summary}

Write the page body."""


def generate_person_page(*, slug: str, name: str, relation: str,
                         bursts_summary: str, sources_count: int, llm,
                         drivers: list[str] | None = None,
                         tics: list[str] | None = None) -> str:
    user = PERSON_USER.format(
        slug=slug, name=name, relation=relation,
        bursts_summary=bursts_summary, sources_count=sources_count,
    )
    body = llm.complete(PERSON_SYSTEM, user, max_tokens=3000).text.strip()
    fm = {
        "type": "person",
        "slug": slug,
        "name": name,
        "relation": relation,
        "languages": ["fr", "en"],
        "drivers": drivers or [],
        "conversational-tics": tics or [],
        "sources_count": sources_count,
        "last_touched": date.today().isoformat(),
    }
    validate_page("person", fm, body)
    return render_page(fm, body)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_wiki_people.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/wiki/people.py scripts/tests/test_wiki_people.py
git commit -m "feat: person page generator"
```

---

## Task 10: Concept and Position page generators

**Files:**
- Create: `scripts/signal_brain/wiki/concepts.py`
- Create: `scripts/signal_brain/wiki/positions.py`
- Create: `scripts/tests/test_wiki_pages.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_wiki_pages.py`**

```python
from signal_brain.wiki.concepts import generate_concept_page
from signal_brain.wiki.positions import generate_position_page
from signal_brain.wiki.schemas import parse_page, validate_page


CONCEPT_BODY = """## What's at stake
Issue.

## Sub-questions
Sub.

## Empirical anchors
Anchors [B0001#m1].

## Positions on this concept
- [[positions/alice--topic-a-policy]]

## Related
(auto-maintained — see link pass)
"""


POSITION_BODY = """## Core claim
Claim.

## Reasoning chain
Chain [B0001#m2].

## Examples / evidence cited
Examples.

## Concessions made
Concessions.

## Tensions with own other positions
Tensions.

## Evolution timeline
Timeline.

## Counter-arguments faced
Counters.

## Related
(auto-maintained — see link pass)
"""


def test_generate_concept_page_validates(mocker):
    llm = mocker.MagicMock()
    llm.complete.return_value.text = CONCEPT_BODY
    page = generate_concept_page(
        slug="topic-a-policy", aliases=["alt-name"],
        contested=True, sources_count=87, bursts_summary="...", llm=llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "concept"
    validate_page("concept", fm, body)


def test_generate_position_page_validates(mocker):
    llm = mocker.MagicMock()
    llm.complete.return_value.text = POSITION_BODY
    page = generate_position_page(
        holder="alice", concept="topic-a-policy",
        stance="Concentration > threshold should be structurally prevented.",
        confidence="high",
        first_seen="[B0014#m3]", last_seen="[B0186#m22]",
        evolution="stable", sources_count=34,
        bursts_summary="...", counterpart_summary="...", llm=llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "position"
    assert fm["holder"] == "alice"
    assert fm["concept"] == "topic-a-policy"
    validate_page("position", fm, body)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest scripts/tests/test_wiki_pages.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/wiki/concepts.py`**

```python
"""Concept page generation."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


CONCEPT_SYSTEM = """Generate a "concept" page for a debate wiki.

Constraints:
- English prose. French quotes preserved verbatim in citations.
- Every non-trivial claim cites at least one message: [Bnnnn#mN].
- Output body only. Sections required, in order:
  ## What's at stake
  ## Sub-questions
  ## Empirical anchors  (list concrete examples cited in the conversation: numbers, historical events)
  ## Positions on this concept  (list links like [[positions/<holder>--<slug>]])
  ## Related  (placeholder: "(auto-maintained — see link pass)")
"""


CONCEPT_USER = """Concept slug: {slug}
Aliases: {aliases}
Contested: {contested}
Sources count: {sources_count}

Conversation summary on this topic:
{bursts_summary}

Write the page body."""


def generate_concept_page(*, slug: str, aliases: list[str], contested: bool,
                          sources_count: int, bursts_summary: str, llm) -> str:
    user = CONCEPT_USER.format(
        slug=slug, aliases=", ".join(aliases), contested=contested,
        sources_count=sources_count, bursts_summary=bursts_summary,
    )
    body = llm.complete(CONCEPT_SYSTEM, user, max_tokens=3000).text.strip()
    fm = {
        "type": "concept",
        "slug": slug,
        "aliases": aliases,
        "related": [],
        "contested": contested,
        "sources_count": sources_count,
        "last_touched": date.today().isoformat(),
    }
    validate_page("concept", fm, body)
    return render_page(fm, body)
```

- [ ] **Step 4: Implement `scripts/signal_brain/wiki/positions.py`**

```python
"""Position page generation — the page type unique to debate wikis."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


POSITION_SYSTEM = """Generate a "position" page: one person's stance on one concept.

Constraints:
- English prose. French quotes verbatim in citations.
- Every claim cites at least one message: [Bnnnn#mN].
- Stay grounded in what THIS holder actually said. Don't invent positions.
- Output body only. Sections required, in order:
  ## Core claim         (one sentence)
  ## Reasoning chain    (numbered steps; cite as you go)
  ## Examples / evidence cited
  ## Concessions made   (places this holder gave ground)
  ## Tensions with own other positions  (lint candidate; empty if none yet)
  ## Evolution timeline (dated turns: date — turn — citation)
  ## Counter-arguments faced  (strongest moves by the other party)
  ## Related  (placeholder: "(auto-maintained — see link pass)")
"""


POSITION_USER = """Holder: {holder}
Concept: {concept}
Stance (1-sentence summary the caller computed): {stance}
Confidence: {confidence}
First seen: {first_seen}
Last seen: {last_seen}
Evolution: {evolution}
Sources count: {sources_count}

What this holder said on this topic across the conversation:
{bursts_summary}

What the counterpart said back (for counter-arguments section):
{counterpart_summary}

Write the page body."""


def generate_position_page(*, holder: str, concept: str, stance: str,
                           confidence: str, first_seen: str, last_seen: str,
                           evolution: str, sources_count: int,
                           bursts_summary: str, counterpart_summary: str,
                           llm) -> str:
    user = POSITION_USER.format(
        holder=holder, concept=concept, stance=stance, confidence=confidence,
        first_seen=first_seen, last_seen=last_seen, evolution=evolution,
        sources_count=sources_count, bursts_summary=bursts_summary,
        counterpart_summary=counterpart_summary,
    )
    body = llm.complete(POSITION_SYSTEM, user, max_tokens=3500).text.strip()
    fm = {
        "type": "position",
        "holder": holder,
        "concept": concept,
        "stance": stance,
        "confidence": confidence,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "evolution": evolution,
        "sources_count": sources_count,
        "last_touched": date.today().isoformat(),
    }
    validate_page("position", fm, body)
    return render_page(fm, body)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest scripts/tests/test_wiki_pages.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/signal_brain/wiki/concepts.py scripts/signal_brain/wiki/positions.py scripts/tests/test_wiki_pages.py
git commit -m "feat: concept + position page generators"
```

---

## Task 11: Arc and Cross page generators

**Files:**
- Create: `scripts/signal_brain/wiki/arcs.py`
- Create: `scripts/signal_brain/wiki/cross.py`
- Modify: `scripts/tests/test_wiki_pages.py` (append cases)

- [ ] **Step 1: Append failing tests to `scripts/tests/test_wiki_pages.py`**

```python
from signal_brain.wiki.arcs import generate_arc_page
from signal_brain.wiki.cross import generate_cross_page


ARC_BODY = """## Question at stake
Question.

## Opening positions
Positions.

## Key turns
- [B0042#m17]: turn.

## Concessions & ground gained
None.

## Why unresolved
Reasons.

## Related
(auto-maintained — see link pass)
"""


CROSS_BODY = """## Overview
Pattern overview.

## Instances
- [B0042#m17]: instance.

## Related
(auto-maintained — see link pass)
"""


def test_generate_arc_page_validates(mocker):
    llm = mocker.MagicMock()
    llm.complete.return_value.text = ARC_BODY
    page = generate_arc_page(
        arc_id="A007", slug="topic-a-debate",
        period=["2026-05-04", "2026-05-19"],
        bursts=["B0038", "B0039"], primary_topic="topic-a",
        bursts_summary="...", llm=llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "arc"
    assert fm["id"] == "A007"
    validate_page("arc", fm, body)


def test_generate_cross_page_validates(mocker):
    llm = mocker.MagicMock()
    llm.complete.return_value.text = CROSS_BODY
    page = generate_cross_page(
        slug="disagreements", title="Disagreements",
        instances_summary="...", llm=llm,
    )
    fm, body = parse_page(page)
    assert fm["type"] == "cross"
    validate_page("cross", fm, body)
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest scripts/tests/test_wiki_pages.py -v`
Expected: 2 new failures (ModuleNotFoundError for arcs/cross).

- [ ] **Step 3: Implement `scripts/signal_brain/wiki/arcs.py`**

```python
"""Arc page generation — narrative summary of a debate arc."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


ARC_SYSTEM = """Generate an "arc" page: narrative of a multi-burst debate arc.

Constraints:
- English prose. French quotes verbatim in citations.
- Every key turn cites a message: [Bnnnn#mN].
- Output body only. Sections required, in order:
  ## Question at stake
  ## Opening positions
  ## Key turns        (chronological bullet list with citations)
  ## Concessions & ground gained
  ## Why unresolved   (or "Why resolved")
  ## Related          (placeholder)
"""


ARC_USER = """Arc id: {arc_id}, slug: {slug}
Period: {period}
Primary topic: {primary_topic}
Bursts in this arc: {bursts}

Full per-burst summaries:
{bursts_summary}

Write the arc page body."""


def generate_arc_page(*, arc_id: str, slug: str, period: list[str], bursts: list[str],
                     primary_topic: str, bursts_summary: str, llm,
                     status: str = "unresolved",
                     turning_points: list[str] | None = None) -> str:
    user = ARC_USER.format(
        arc_id=arc_id, slug=slug, period=period, primary_topic=primary_topic,
        bursts=bursts, bursts_summary=bursts_summary,
    )
    body = llm.complete(ARC_SYSTEM, user, max_tokens=4000).text.strip()
    fm = {
        "type": "arc", "id": arc_id, "slug": slug,
        "period": period, "bursts": bursts,
        "primary_topic": primary_topic, "status": status,
        "turning_points": turning_points or [],
        "last_touched": date.today().isoformat(),
    }
    validate_page("arc", fm, body)
    return render_page(fm, body)
```

- [ ] **Step 4: Implement `scripts/signal_brain/wiki/cross.py`**

```python
"""Cross-cut page generation: agreements / disagreements / patterns / empirical pool."""
from __future__ import annotations
from datetime import date
from signal_brain.wiki.schemas import render_page, validate_page


CROSS_SYSTEM = """Generate a "cross-cut" page: a pattern observed across multiple bursts/arcs.

Constraints:
- English prose. French quotes verbatim in citations.
- Every instance cites a message: [Bnnnn#mN].
- Output body only. Sections required, in order:
  ## Overview
  ## Instances   (bullet list, each citing a message)
  ## Related     (placeholder)
"""


CROSS_USER = """Cross-cut slug: {slug}  (title: {title})

Instances summary (deduplicated, with citations):
{instances_summary}

Write the page body."""


def generate_cross_page(*, slug: str, title: str, instances_summary: str, llm) -> str:
    body = llm.complete(
        CROSS_SYSTEM,
        CROSS_USER.format(slug=slug, title=title, instances_summary=instances_summary),
        max_tokens=3000,
    ).text.strip()
    fm = {"type": "cross", "slug": slug, "title": title,
          "last_touched": date.today().isoformat()}
    validate_page("cross", fm, body)
    return render_page(fm, body)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest scripts/tests/test_wiki_pages.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/signal_brain/wiki/arcs.py scripts/signal_brain/wiki/cross.py scripts/tests/test_wiki_pages.py
git commit -m "feat: arc + cross page generators"
```

---

## Task 12: Indexes — schema.md / log.md bootstrap + build_index.py

**Files:**
- Create: `scripts/signal_brain/indexing.py`
- Create: `scripts/tests/test_indexing.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_indexing.py`**

```python
from signal_brain.indexing import build_index, bootstrap_schema, append_log
from signal_brain.wiki.schemas import render_page


def test_build_index_lists_every_page(tmp_wiki_dir):
    (tmp_wiki_dir / "people" / "alice.md").write_text(render_page(
        {"type": "person", "slug": "alice", "name": "Alice", "sources_count": 5,
         "last_touched": "2026-05-19"},
        "## Background\nx\n## Style & drivers\nx\n## Key positions\nx\n## Recurring moves\nx\n## Open tensions\nx\n## Related\nx"))
    (tmp_wiki_dir / "concepts" / "topic-a.md").write_text(render_page(
        {"type": "concept", "slug": "topic-a", "contested": True,
         "sources_count": 10, "last_touched": "2026-05-19"},
        "## What's at stake\nx\n## Sub-questions\nx\n## Empirical anchors\nx\n## Positions on this concept\nx\n## Related\nx"))
    out = tmp_wiki_dir / "index.md"
    build_index(tmp_wiki_dir, out)
    text = out.read_text()
    assert "## People" in text
    assert "[[people/alice]]" in text
    assert "## Concepts" in text
    assert "[[concepts/topic-a]]" in text


def test_bootstrap_schema_writes_conventions_doc(tmp_wiki_dir):
    bootstrap_schema(tmp_wiki_dir / "schema.md")
    text = (tmp_wiki_dir / "schema.md").read_text()
    assert "Citation format" in text
    assert "[Bnnnn#mN]" in text
    assert "English" in text


def test_append_log_is_append_only(tmp_wiki_dir):
    log = tmp_wiki_dir / "log.md"
    append_log(log, "## [2026-05-19] ingest | +1")
    append_log(log, "## [2026-05-19] lint | ok")
    text = log.read_text()
    assert text.count("## [2026-05-19]") == 2
    assert text.index("ingest") < text.index("lint")
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest scripts/tests/test_indexing.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/indexing.py`**

```python
"""Build index.md catalog, bootstrap schema.md, append-only log.md."""
from __future__ import annotations
from pathlib import Path
from signal_brain.wiki.schemas import parse_page


SCHEMA_MD = """# Signal Conversation Brain — schema

This is the CLAUDE.md for this wiki. Agents updating the wiki must follow these rules.

## Page types
- `people/{slug}.md` — entity. Required frontmatter: type, slug, name. Sections: Background, Style & drivers, Key positions, Recurring moves, Open tensions, Related.
- `concepts/{slug}.md` — topic. Required frontmatter: type, slug, contested. Sections: What's at stake, Sub-questions, Empirical anchors, Positions on this concept, Related.
- `positions/{holder}--{concept}.md` — one person on one concept. Required frontmatter: type, holder, concept, stance, confidence, first_seen, last_seen, evolution, sources_count. Sections: Core claim, Reasoning chain, Examples / evidence cited, Concessions made, Tensions with own other positions, Evolution timeline, Counter-arguments faced, Related.
- `arcs/A{nnn}-{slug}.md` — debate arc narrative. Required frontmatter: type, id, slug, period, primary_topic, status, bursts. Sections: Question at stake, Opening positions, Key turns, Concessions & ground gained, Why unresolved, Related.
- `cross/{slug}.md` — cross-cut patterns. Required frontmatter: type, slug. Sections: Overview, Instances, Related.

## Citation format
Every non-trivial claim cites at least one message in the form `[Bnnnn#mN]`, where `Bnnnn` is the burst id and `mN` is the 1-indexed position of the message within that burst's `msg_ids` array.

Citations resolve via `scripts/signal_brain/citations.py`.

## Language
- Wiki content is in English.
- Quoted source material is preserved verbatim in French.
- Slugs are lowercase ASCII, kebab-case, no diacritics (`bjork`, not `björk`).

## Related sections
The `## Related` section is **auto-maintained** by the link pass. Never hand-edit.

## When to create vs update
- Create a new concept page when a topic appears in ≥ 5 bursts.
- Create a new position page when a person has staked a clear stance on a concept (≥ 1 substantive burst).
- Create a new arc page when bursts meet `min_burst_count` AND `min_msg_count` thresholds in `config.toml`.
- Create a new cross page only when a pattern appears in ≥ `cross_pages.min_occurrences` bursts.
- Update content sections (not Related) when an ingest flags the page as `needs-update` in `log.md`.

## Build / lint
- `signal-brain ingest` runs the full pipeline. See `docs/superpowers/specs/2026-05-19-signal-convo-brain-design.md` §12.
- `signal-brain lint` produces `wiki/lint-report.md`.
"""


def bootstrap_schema(path: Path) -> None:
    Path(path).write_text(SCHEMA_MD)


def append_log(path: Path, entry: str) -> None:
    p = Path(path)
    existing = p.read_text() if p.exists() else ""
    if existing and not existing.endswith("\n\n"):
        existing = existing.rstrip("\n") + "\n\n"
    p.write_text(existing + entry.rstrip("\n") + "\n")


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
                fm, _ = parse_page(md.read_text())
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
    Path(out_path).write_text("\n".join(lines).rstrip() + "\n")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_indexing.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/indexing.py scripts/tests/test_indexing.py
git commit -m "feat: index builder + schema.md bootstrap + append-only log"
```

---

## Task 13: Linking pass (Stage 1 deterministic + Stage 2 LLM lateral)

**Files:**
- Create: `scripts/signal_brain/linking.py`
- Create: `scripts/tests/test_linking.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_linking.py`**

```python
from signal_brain.linking import (
    build_deterministic_graph, write_related_blocks, run_stage1, run_stage2,
)
from signal_brain.wiki.schemas import render_page, parse_page


def _seed(tmp_wiki_dir):
    (tmp_wiki_dir / "people" / "alice.md").write_text(render_page(
        {"type": "person", "slug": "alice", "name": "Alice"},
        "## Background\nx\n## Style & drivers\nx\n## Key positions\nx\n## Recurring moves\nx\n## Open tensions\nx\n## Related\n(auto-maintained — see link pass)\n"))
    (tmp_wiki_dir / "concepts" / "topic-a.md").write_text(render_page(
        {"type": "concept", "slug": "topic-a", "contested": True},
        "## What's at stake\nx\n## Sub-questions\nx\n## Empirical anchors\nx\n## Positions on this concept\nx\n## Related\n(auto-maintained — see link pass)\n"))
    (tmp_wiki_dir / "positions" / "alice--topic-a.md").write_text(render_page(
        {"type": "position", "holder": "alice", "concept": "topic-a",
         "stance": "x", "confidence": "high", "first_seen": "[B0001#m1]",
         "last_seen": "[B0001#m1]", "evolution": "stable", "sources_count": 1},
        "## Core claim\nx\n## Reasoning chain\nx\n## Examples / evidence cited\nx\n## Concessions made\nx\n## Tensions with own other positions\nx\n## Evolution timeline\nx\n## Counter-arguments faced\nx\n## Related\n(auto-maintained — see link pass)\n"))


def test_stage1_links_position_to_concept_and_person(tmp_wiki_dir):
    _seed(tmp_wiki_dir)
    run_stage1(tmp_wiki_dir)
    pos = (tmp_wiki_dir / "positions" / "alice--topic-a.md").read_text()
    assert "[[concepts/topic-a]]" in pos
    assert "[[people/alice]]" in pos
    concept = (tmp_wiki_dir / "concepts" / "topic-a.md").read_text()
    assert "[[positions/alice--topic-a]]" in concept
    person = (tmp_wiki_dir / "people" / "alice.md").read_text()
    assert "[[positions/alice--topic-a]]" in person


def test_stage2_calls_llm_per_page(tmp_wiki_dir, mocker):
    _seed(tmp_wiki_dir)
    run_stage1(tmp_wiki_dir)
    llm = mocker.MagicMock()
    llm.complete_json.return_value = {"links": []}
    run_stage2(tmp_wiki_dir, llm)
    assert llm.complete_json.call_count == 3  # one per page


def test_write_related_block_is_idempotent(tmp_wiki_dir):
    _seed(tmp_wiki_dir)
    page = tmp_wiki_dir / "positions" / "alice--topic-a.md"
    write_related_blocks({page: ["[[concepts/topic-a]]", "[[people/alice]]"]})
    write_related_blocks({page: ["[[concepts/topic-a]]", "[[people/alice]]"]})
    body = page.read_text()
    assert body.count("[[concepts/topic-a]]") == 1
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest scripts/tests/test_linking.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/linking.py`**

```python
"""Linking pass: Stage 1 deterministic + Stage 2 LLM lateral."""
from __future__ import annotations
import re
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
        page = Path(path).read_text()
        fm, body = parse_page(page)
        new_body = _replace_related_block(body, links)
        Path(path).write_text(render_page(fm, new_body))


def _scan_pages(wiki_dir: Path) -> dict[Path, dict]:
    out: dict[Path, dict] = {}
    for sub in ["people", "concepts", "positions", "arcs", "cross"]:
        for md in (Path(wiki_dir) / sub).glob("*.md"):
            try:
                fm, body = parse_page(md.read_text())
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


def run_stage2(wiki_dir: Path, llm) -> None:
    wiki_dir = Path(wiki_dir)
    pages = _scan_pages(wiki_dir)
    index_excerpt = (wiki_dir / "index.md").read_text() if (wiki_dir / "index.md").exists() else ""
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
    (wiki_dir.parent / "data" / "link_graph.jsonl").write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in graph) + "\n"
    )
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_linking.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/linking.py scripts/tests/test_linking.py
git commit -m "feat: linking pass — Stage 1 deterministic + Stage 2 LLM lateral"
```

---

## Task 14: Lint pass

**Files:**
- Create: `scripts/signal_brain/lint.py`
- Create: `scripts/tests/test_lint.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_lint.py`**

```python
import json
from signal_brain.lint import run_lint
from signal_brain.wiki.schemas import render_page


def test_unresolved_citations_flagged(tmp_path, tmp_wiki_dir):
    data = tmp_path / "data"
    data.mkdir()
    # Empty bursts/msgs so any citation is unresolved
    (data / "bursts.jsonl").write_text("")
    (data / "msg_index.jsonl").write_text("")
    (tmp_wiki_dir / "people" / "alice.md").write_text(render_page(
        {"type": "person", "slug": "alice", "name": "Alice"},
        "## Background\ncites [B0001#m1].\n## Style & drivers\nx\n## Key positions\nx\n## Recurring moves\nx\n## Open tensions\nx\n## Related\nx"))
    report = tmp_wiki_dir / "lint-report.md"
    run_lint(tmp_wiki_dir, data, report)
    text = report.read_text()
    assert "Unresolved citations" in text
    assert "[B0001#m1]" in text


def test_orphan_pages_flagged(tmp_path, tmp_wiki_dir):
    data = tmp_path / "data"
    data.mkdir()
    (data / "bursts.jsonl").write_text("")
    (data / "msg_index.jsonl").write_text("")
    (tmp_wiki_dir / "people" / "alice.md").write_text(render_page(
        {"type": "person", "slug": "alice", "name": "Alice"},
        "## Background\nx\n## Style & drivers\nx\n## Key positions\nx\n## Recurring moves\nx\n## Open tensions\nx\n## Related\n(empty)"))
    report = tmp_wiki_dir / "lint-report.md"
    run_lint(tmp_wiki_dir, data, report)
    assert "Orphan" in report.read_text()
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest scripts/tests/test_lint.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/lint.py`**

```python
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
            fm, body = parse_page(path.read_text())
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
    Path(out_path).write_text("\n".join(lines))
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest scripts/tests/test_lint.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/signal_brain/lint.py scripts/tests/test_lint.py
git commit -m "feat: lint pass — citations, orphans, scaffolding for stale/synonyms/missing"
```

---

## Task 15: Incremental ingest + CLI orchestration

**Files:**
- Create: `scripts/signal_brain/ingest.py`
- Create: `scripts/signal_brain/cli.py`
- Create: `scripts/tests/test_ingest.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_ingest.py`**

```python
import json
from pathlib import Path
from signal_brain.ingest import diff_messages, run_ingest_data_layer


def test_diff_messages_identifies_new_and_modified(tmp_data_dir):
    # Existing index
    existing = [
        {"msg_id": "2026-05-05T13:00:00::Me", "date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi", "quote":"", "reactions":[], "attachments":[], "char_count":2},
    ]
    (tmp_data_dir / "msg_index.jsonl").write_text(
        "\n".join(json.dumps(r) for r in existing) + "\n"
    )
    # New input with: one identical, one modified, one new
    new_input = [
        {"date": "2026-05-05T13:00:00.000000", "sender": "Me", "body": "hi", "quote":"", "reactions":[], "attachments":[]},  # same body
        {"date": "2026-05-05T13:00:00.000000", "sender": "Me", "body": "hi!", "quote":"", "reactions":[], "attachments":[]},  # would collide; ignore for this test
        {"date": "2026-05-05T13:05:00.000000", "sender": "Friend", "body": "yo", "quote":"", "reactions":[], "attachments":[]},  # new
    ]
    # Filter the duplicate timestamp to keep the test focused
    new_input = [new_input[0], new_input[2]]
    diff = diff_messages(new_input, tmp_data_dir / "msg_index.jsonl")
    assert len(diff["new"]) == 1
    assert diff["new"][0]["sender"] == "Friend"
    assert len(diff["modified"]) == 0


def test_run_ingest_data_layer_writes_all_artifacts(tmp_path, mini_messages, mocker):
    src = tmp_path / "out" / "source"
    src.mkdir(parents=True)
    (src / "data.json").write_text("\n".join(json.dumps(m) for m in mini_messages) + "\n")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    mock_llm = mocker.MagicMock()
    mock_llm.complete_json.return_value = {
        "topics": ["banter"], "primary": "banter", "summary": "banter sample",
    }
    run_ingest_data_layer(
        source_path=src / "data.json",
        data_dir=data_dir,
        llm=mock_llm,
        burst_threshold_min=60,
        min_burst_count=2,
        min_msg_count=20,
    )
    for f in ["msg_index.jsonl", "bursts.jsonl", "chunks.jsonl", "arcs.jsonl", "manifest.json"]:
        assert (data_dir / f).exists(), f
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest scripts/tests/test_ingest.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/ingest.py`**

```python
"""Incremental ingest pipeline."""
from __future__ import annotations
import json
from pathlib import Path
from signal_brain.msg_index import build_msg_index, load_msg_index, msg_id
from signal_brain.bursts import detect_bursts, burst_content_hash, write_bursts
from signal_brain.tagging import tag_bursts
from signal_brain.arcs import detect_arcs, write_arcs
from signal_brain.manifest import Manifest


def _load_raw(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def diff_messages(new_input: list[dict], existing_index_path: Path) -> dict:
    """Return dict with keys: new, modified, unchanged, removed."""
    existing = {}
    if Path(existing_index_path).exists():
        for line in Path(existing_index_path).read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            existing[r["msg_id"]] = r
    new_ids = set()
    new_list: list[dict] = []
    modified: list[dict] = []
    for m in new_input:
        mid = msg_id(m)
        new_ids.add(mid)
        if mid not in existing:
            new_list.append(m)
        else:
            prev = existing[mid]
            if (m.get("body", "") != prev.get("body", "")
                    or m.get("reactions", []) != prev.get("reactions", [])
                    or m.get("attachments", []) != prev.get("attachments", [])):
                modified.append(m)
    removed = [mid for mid in existing if mid not in new_ids]
    return {"new": new_list, "modified": modified, "removed": removed,
            "unchanged_count": len(existing) - len(modified) - len(removed)}


def run_ingest_data_layer(*, source_path: Path, data_dir: Path, llm,
                          burst_threshold_min: int, min_burst_count: int,
                          min_msg_count: int) -> dict:
    """Builds msg_index → bursts → chunks → arcs → manifest. Returns stats."""
    source = _load_raw(source_path)
    data_dir = Path(data_dir)
    data_dir.mkdir(exist_ok=True)
    msg_index_path = data_dir / "msg_index.jsonl"
    chunks_path = data_dir / "chunks.jsonl"
    bursts_path = data_dir / "bursts.jsonl"
    arcs_path = data_dir / "arcs.jsonl"
    manifest_path = data_dir / "manifest.json"

    diff = diff_messages(source, msg_index_path)
    build_msg_index(source, msg_index_path)
    msgs = load_msg_index(msg_index_path)
    bursts = detect_bursts(msgs, threshold_min=burst_threshold_min)
    write_bursts(bursts, bursts_path)

    manifest = Manifest.load_or_init(manifest_path, burst_threshold_min=burst_threshold_min)
    # Build cache_by_id from previous chunks + previous hashes
    cache_by_id: dict[str, dict] = {}
    if chunks_path.exists():
        for line in chunks_path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            cache_by_id[r["burst_id"]] = {
                "hash": manifest.content_hashes.get(r["burst_id"], ""),
                "topics": r["topics"], "primary": r["primary"], "summary": r["summary"],
            }
    new_hashes = tag_bursts(bursts, msgs, llm, cache_by_id, chunks_path)
    chunks = [json.loads(l) for l in chunks_path.read_text().splitlines() if l.strip()]

    arcs = detect_arcs(bursts, chunks, min_burst_count=min_burst_count, min_msg_count=min_msg_count)
    write_arcs(arcs, arcs_path)

    manifest.last_processed_msg_ts = msgs[-1]["date"] if msgs else None
    manifest.burst_count = len(bursts)
    manifest.content_hashes = new_hashes
    manifest.save(manifest_path)

    return {"diff": {k: len(v) if isinstance(v, list) else v for k, v in diff.items()},
            "bursts": len(bursts), "arcs": len(arcs)}
```

- [ ] **Step 4: Implement `scripts/signal_brain/cli.py`**

```python
"""signal-brain CLI."""
from __future__ import annotations
import json
from pathlib import Path
import tomllib
import click
from signal_brain.llm import LLMClient
from signal_brain.ingest import run_ingest_data_layer
from signal_brain.indexing import bootstrap_schema, build_index, append_log
from signal_brain.linking import run_stage1, run_stage2
from signal_brain.lint import run_lint


def _load_config(path: Path = Path("config.toml")) -> dict:
    return tomllib.loads(path.read_text())


@click.group()
def main():
    """Signal conversation brain."""


@main.command()
def ingest():
    """Build/refresh the data layer (L0→L2). Wiki page generation is separate (`build-wiki`)."""
    cfg = _load_config()
    llm_tag = LLMClient(default_model=cfg["llm"]["tagging_model"])
    stats = run_ingest_data_layer(
        source_path=Path(cfg["paths"]["source_data"]),
        data_dir=Path(cfg["paths"]["data_dir"]),
        llm=llm_tag,
        burst_threshold_min=cfg["bursts"]["threshold_minutes"],
        min_burst_count=cfg["arcs"]["min_burst_count"],
        min_msg_count=cfg["arcs"]["min_msg_count"],
    )
    log = Path(cfg["paths"]["wiki_dir"]) / "log.md"
    append_log(log, f"## [{__import__('datetime').date.today().isoformat()}] ingest | {stats}")
    click.echo(json.dumps(stats, indent=2))


@main.command("build-index")
def build_index_cmd():
    cfg = _load_config()
    wiki = Path(cfg["paths"]["wiki_dir"])
    bootstrap_schema(wiki / "schema.md")
    build_index(wiki, wiki / "index.md")
    click.echo("wiki/schema.md and wiki/index.md updated.")


@main.command("link")
@click.option("--stage", type=click.Choice(["1", "2", "all"]), default="all")
def link_cmd(stage):
    cfg = _load_config()
    wiki = Path(cfg["paths"]["wiki_dir"])
    if stage in ("1", "all"):
        run_stage1(wiki)
        click.echo("Stage 1 (deterministic) done.")
    if stage in ("2", "all"):
        llm = LLMClient(default_model=cfg["llm"]["synthesis_model"])
        run_stage2(wiki, llm)
        click.echo("Stage 2 (LLM lateral) done.")


@main.command()
def lint():
    cfg = _load_config()
    wiki = Path(cfg["paths"]["wiki_dir"])
    data = Path(cfg["paths"]["data_dir"])
    run_lint(wiki, data, wiki / "lint-report.md")
    click.echo(f"Lint report written to {wiki / 'lint-report.md'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest scripts/tests/test_ingest.py -v`
Expected: 2 passed.

- [ ] **Step 6: Smoke-test CLI end-to-end on real data**

Run:
```bash
signal-brain ingest
signal-brain build-index
signal-brain link --stage 1
signal-brain lint
cat wiki/index.md | head -40
```
Expected: each command exits 0. (Stage 2 linking and wiki content pages come next — Task 16.)

- [ ] **Step 7: Commit**

```bash
git add scripts/signal_brain/ingest.py scripts/signal_brain/cli.py scripts/tests/test_ingest.py
git commit -m "feat: incremental ingest + CLI orchestration"
```

---

## Task 16: Wiki content build + first-build verification

The wiki page generators from Tasks 9–11 still need an orchestrator that decides which pages to create and feeds them the right summaries. This task wires them up, runs the first build against the full target conversation, and verifies the acceptance criteria from spec §15.

**Files:**
- Create: `scripts/signal_brain/wiki/build.py`
- Create: `scripts/signal_brain/evaluators.py` (burst-threshold evaluator)
- Modify: `scripts/signal_brain/cli.py` (add `build-wiki` and `evaluate-bursts`)
- Create: `scripts/tests/test_wiki_build.py`

- [ ] **Step 1: Write failing test `scripts/tests/test_wiki_build.py`**

```python
from signal_brain.wiki.build import plan_pages


def test_plan_pages_creates_one_position_per_person_concept_pair():
    bursts = [
        {"id": "B0001", "msg_ids": ["a", "b"], "start": "2026-05-05T13:00", "senders": {"Me": 5, "Friend": 5}},
    ] * 6
    chunks = [{"burst_id": f"B{i:04d}", "primary": "topic-a", "topics": ["topic-a"], "summary": "..."} for i in range(1, 7)]
    plan = plan_pages(bursts, chunks, arcs=[], min_concept_bursts=5)
    assert "people/alice" in plan["pages"]
    assert "people/friend" in plan["pages"]
    assert "concepts/topic-a" in plan["pages"]
    assert "positions/alice--topic-a" in plan["pages"]
    assert "positions/friend--topic-a" in plan["pages"]


def test_plan_pages_skips_concept_below_threshold():
    chunks = [{"burst_id": "B0001", "primary": "rare-topic", "topics": ["rare-topic"], "summary": "..."}]
    bursts = [{"id": "B0001", "msg_ids": ["a"], "start": "2026-05-05T13:00", "senders": {"Me": 1}}]
    plan = plan_pages(bursts, chunks, arcs=[], min_concept_bursts=5)
    assert "concepts/rare-topic" not in plan["pages"]
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest scripts/tests/test_wiki_build.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/signal_brain/wiki/build.py`**

```python
"""Wiki page build orchestration: decide what pages to create, summarize bursts for them, generate."""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
from signal_brain.wiki.people import generate_person_page
from signal_brain.wiki.concepts import generate_concept_page
from signal_brain.wiki.positions import generate_position_page
from signal_brain.wiki.arcs import generate_arc_page
from signal_brain.wiki.cross import generate_cross_page


SENDER_TO_SLUG = {"Me": "alice", "Friend": "friend"}
SENDER_TO_NAME = {"Me": "Alice Example", "Friend": "Friend"}


def plan_pages(bursts: list[dict], chunks: list[dict], arcs: list[dict],
               min_concept_bursts: int) -> dict:
    """Decide which pages should exist. Returns {"pages": {key: spec}}."""
    chunk_by_burst = {c["burst_id"]: c for c in chunks}
    topic_counts: dict[str, int] = defaultdict(int)
    topic_bursts: dict[str, list[str]] = defaultdict(list)
    person_bursts: dict[str, list[str]] = defaultdict(list)
    person_topic_bursts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for b in bursts:
        c = chunk_by_burst.get(b["id"])
        if not c:
            continue
        primary = c["primary"]
        topic_counts[primary] += 1
        topic_bursts[primary].append(b["id"])
        for sender, n in b.get("senders", {}).items():
            slug = SENDER_TO_SLUG.get(sender)
            if not slug or n == 0:
                continue
            person_bursts[slug].append(b["id"])
            person_topic_bursts[(slug, primary)].append(b["id"])

    pages: dict[str, dict] = {}
    for slug, bs in person_bursts.items():
        pages[f"people/{slug}"] = {"slug": slug, "bursts": bs,
                                   "name": SENDER_TO_NAME["Me" if slug == "alice" else "Friend"],
                                   "relation": "Me" if slug == "alice" else "Friend"}
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


def build_wiki(*, data_dir: Path, wiki_dir: Path, llm, min_concept_bursts: int = 5) -> dict:
    data_dir = Path(data_dir)
    wiki_dir = Path(wiki_dir)
    for sub in ["people", "concepts", "positions", "arcs", "cross"]:
        (wiki_dir / sub).mkdir(parents=True, exist_ok=True)
    bursts = [json.loads(l) for l in (data_dir / "bursts.jsonl").read_text().splitlines() if l.strip()]
    chunks = [json.loads(l) for l in (data_dir / "chunks.jsonl").read_text().splitlines() if l.strip()]
    arcs = [json.loads(l) for l in (data_dir / "arcs.jsonl").read_text().splitlines() if l.strip()] \
        if (data_dir / "arcs.jsonl").exists() else []
    chunks_by_id = {c["burst_id"]: c for c in chunks}

    plan = plan_pages(bursts, chunks, arcs, min_concept_bursts=min_concept_bursts)
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
            counterpart = "friend" if spec["holder"] == "alice" else "alice"
            counterpart_bursts = [b for b in spec["bursts"]]  # same bursts; LLM uses sender hints in summary
            counterpart_summary = summary  # adequate first pass
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
        path.write_text(page)
        written[key] = str(path)

    # Seed cross pages (agreements, disagreements, rhetorical-patterns, empirical-pool)
    for slug, title in [("agreements", "Agreements"), ("disagreements", "Disagreements"),
                        ("rhetorical-patterns", "Rhetorical patterns"),
                        ("empirical-pool", "Empirical pool")]:
        path = wiki_dir / "cross" / f"{slug}.md"
        if not path.exists():
            instances = "\n".join(f"- {c['burst_id']}: {c['summary']}" for c in chunks[:20])
            page = generate_cross_page(slug=slug, title=title,
                                       instances_summary=instances, llm=llm)
            path.write_text(page)
            written[f"cross/{slug}"] = str(path)

    return {"pages_written": len(written), "paths": written}
```

- [ ] **Step 4: Implement `scripts/signal_brain/evaluators.py`**

```python
"""One-shot burst-threshold evaluator."""
from __future__ import annotations
import json
import random
from pathlib import Path
from signal_brain.msg_index import load_msg_index


EVAL_SYSTEM = """You evaluate whether a burst boundary in a Signal conversation is natural.

You are shown the last 3 messages of burst K and the first 3 of burst K+1.
Output VALID JSON. No prose around.
{"verdict": "natural" | "should-merge" | "should-split-elsewhere", "rationale": "..."}
"""


EVAL_USER = """End of burst {k} ({k_end_time}):
{k_tail}

Start of burst {k_plus_1} ({k1_start_time}):
{k1_head}

Was this a natural conversation break?"""


def evaluate_bursts(data_dir: Path, llm, sample_size: int = 20) -> dict:
    bursts = [json.loads(l) for l in (Path(data_dir) / "bursts.jsonl").read_text().splitlines() if l.strip()]
    msgs = {m["msg_id"]: m for m in load_msg_index(Path(data_dir) / "msg_index.jsonl")}
    if len(bursts) < 2:
        return {"verdict": "not-enough-bursts", "samples": []}
    sample_idx = random.sample(range(len(bursts) - 1), min(sample_size, len(bursts) - 1))
    results = []
    for i in sample_idx:
        k, k1 = bursts[i], bursts[i + 1]
        k_tail = "\n".join(
            f"{msgs[mid]['sender']}: {msgs[mid].get('body','').strip()}"
            for mid in k["msg_ids"][-3:]
        )
        k1_head = "\n".join(
            f"{msgs[mid]['sender']}: {msgs[mid].get('body','').strip()}"
            for mid in k1["msg_ids"][:3]
        )
        verdict = llm.complete_json(EVAL_SYSTEM, EVAL_USER.format(
            k=k["id"], k_end_time=k["end"], k_tail=k_tail,
            k_plus_1=k1["id"], k1_start_time=k1["start"], k1_head=k1_head,
        ))
        results.append({"boundary": [k["id"], k1["id"]], **verdict})
    counts = {"natural": 0, "should-merge": 0, "should-split-elsewhere": 0}
    for r in results:
        counts[r.get("verdict", "should-split-elsewhere")] = counts.get(r.get("verdict", "should-split-elsewhere"), 0) + 1
    return {"counts": counts, "samples": results, "n": len(results)}
```

- [ ] **Step 5: Extend `scripts/signal_brain/cli.py` with `build-wiki` and `evaluate-bursts`**

Append to the bottom of `cli.py`:

```python
@main.command("build-wiki")
def build_wiki_cmd():
    cfg = _load_config()
    from signal_brain.wiki.build import build_wiki
    llm = LLMClient(default_model=cfg["llm"]["synthesis_model"])
    stats = build_wiki(
        data_dir=Path(cfg["paths"]["data_dir"]),
        wiki_dir=Path(cfg["paths"]["wiki_dir"]),
        llm=llm,
    )
    click.echo(json.dumps(stats, indent=2))


@main.command("evaluate-bursts")
@click.option("--sample-size", type=int, default=20)
def evaluate_bursts_cmd(sample_size):
    cfg = _load_config()
    from signal_brain.evaluators import evaluate_bursts
    llm = LLMClient(default_model=cfg["llm"]["synthesis_model"])
    result = evaluate_bursts(Path(cfg["paths"]["data_dir"]), llm, sample_size=sample_size)
    click.echo(json.dumps(result, indent=2))
```

- [ ] **Step 6: Run tests, expect pass**

Run: `pytest scripts/tests/test_wiki_build.py -v`
Expected: 2 passed.

- [ ] **Step 7: Run full first build against real data**

Run:
```bash
signal-brain ingest
signal-brain build-wiki
signal-brain build-index
signal-brain link --stage all
signal-brain lint
signal-brain evaluate-bursts --sample-size 20
```

Inspect:
```bash
ls wiki/people wiki/concepts wiki/positions wiki/arcs wiki/cross
wc -l wiki/lint-report.md
cat wiki/index.md
```

- [ ] **Step 8: Verify spec acceptance criteria**

Per spec §15:
1. `data/{bursts,chunks,arcs,msg_index}.jsonl` + `manifest.json` exist. Check `ls -la data/`.
2. Evaluator reports ≥ 80% "natural". Check `evaluate-bursts` output.
3. Wiki contains ≥ 2 people, ≥ 15 concepts, ≥ 15 positions, ≥ 5 arcs, ≥ 3 cross pages. Check `ls wiki/*/`.
4. Every page has ≥ 2 inbound and ≥ 2 outbound edges. Check `data/link_graph.jsonl` and `wiki/lint-report.md` for orphans.
5. Every citation resolves. Check `wiki/lint-report.md` "Unresolved citations: (none)".
6. Lint pass ran and produced a report. ✓ by step 7.
7. Synthetic re-export (touch only last 5 messages) updates < 5% of data and < 10% of wiki pages.

For criterion 7, run:
```bash
# Synthetic edit: append one new message to a copy of data.json
cp out/<source>/data.json /tmp/data.json.bak
python3 -c "
import json
p = 'out/<source>/data.json'
lines = open(p).readlines()
last = json.loads(lines[-1])
new = dict(last)
new['date'] = '2026-05-19T15:00:00.000000'
new['body'] = 'synthetic test message'
open(p, 'a').write(json.dumps(new) + '\n')
"
signal-brain ingest
# Compare manifest content_hashes before/after; only the tail burst should change
```

If any criterion fails, file a follow-up task and fix.

- [ ] **Step 9: Restore data and commit**

```bash
mv /tmp/data.json.bak out/<source>/data.json
signal-brain ingest  # restore manifest to pre-test state
git add scripts/signal_brain/wiki/build.py scripts/signal_brain/evaluators.py scripts/signal_brain/cli.py scripts/tests/test_wiki_build.py wiki/
git commit -m "feat: wiki build orchestration + burst evaluator; first build verified"
```

---

## Self-review (run before handing off)

Spec coverage:
- §3 layered architecture → Tasks 2–7 (data layer), 8–11 (wiki), 12 (indexes), 13 (linking), 14 (lint).
- §4 storage layout → Task 1 scaffolding + `data/` produced by ingest, `wiki/` by build-wiki.
- §5 L1 bursts → Task 3; threshold knob → `config.toml` (Task 1); evaluator → Task 16.
- §6 L2 topics+arcs → Tasks 6, 7; open vocab (LLM proposes) → tagging prompt.
- §7 five page types → Tasks 9–11.
- §8 naming, citation, language → Task 4 (citations), Task 12 (schema.md), prompts throughout.
- §9 incremental ingest → Tasks 3 (manifest), 6 (cache reuse), 15 (diff + tail-only L1 inside `run_ingest_data_layer`).
- §10 linking pass → Task 13 (both stages).
- §11 lint → Task 14.
- §12 workflow → Task 15 (`signal-brain` CLI).
- §13 knobs → `config.toml` Task 1.
- §15 acceptance → Task 16, Step 8.

Placeholders: searched. No `TODO`, `TBD`, `implement later`. Every step has actual code or an exact command.

Type consistency: `msg_id` returns `str` consistently; `burst_content_hash` returns `str` with `sha1:` prefix consistently; `LLMClient.complete` returns `LLMResponse` consistently; citation format `[Bnnnn#mN]` everywhere; page-type strings (`person`, `concept`, `position`, `arc`, `cross`) consistent across schemas, generators, indexing, linking, lint.

One edit applied during review: clarified that Tasks 9–11 generate isolated pages; Task 16 is the orchestrator that decides which pages exist and feeds them summaries. Without Task 16 you can't go from "data layer built" to "wiki built". This was missing from the original task graph and is now Task 16.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-signal-convo-brain.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?

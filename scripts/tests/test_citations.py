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
    (tmp_data_dir / "bursts.jsonl").write_text("\n".join(json.dumps(b) for b in bursts), encoding="utf-8")
    (tmp_data_dir / "msg_index.jsonl").write_text("\n".join(json.dumps(m) for m in msgs), encoding="utf-8")
    msg = resolve_citation("[B0001#m1]", tmp_data_dir)
    assert msg["sender"] == "Me"
    msg2 = resolve_citation("[B0001#m2]", tmp_data_dir)
    assert msg2["sender"] == "Friend"


def test_resolve_raises_on_missing(tmp_data_dir):
    (tmp_data_dir / "bursts.jsonl").write_text("", encoding="utf-8")
    (tmp_data_dir / "msg_index.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(UnresolvedCitation):
        resolve_citation("[B0001#m1]", tmp_data_dir)


def test_find_citations_in_markdown():
    text = "Alice argues X [B0042#m17] but Friend [B0042#m18] disagrees."
    assert find_citations(text) == ["[B0042#m17]", "[B0042#m18]"]

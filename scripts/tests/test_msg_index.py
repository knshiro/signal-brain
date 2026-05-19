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
    assert first["msg_id"].endswith("::Me") or first["msg_id"].endswith("::Friend")


def test_build_msg_index_deduplicates_on_msg_id(tmp_data_dir):
    duplicates = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Me", "body": "hi"},
        {"date": "2026-05-05T13:18:00.000000", "sender": "Me", "body": "hi"},
    ]
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(duplicates, out)
    assert len(out.read_text().splitlines()) == 1

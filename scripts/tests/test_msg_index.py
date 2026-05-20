import json
from signal_brain.anonymize import compile_scrubber
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


def test_build_msg_index_scrubs_body_when_scrubber_provided(tmp_data_dir):
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "Hey Ugo, look at this", "quote": "", "reactions": [], "attachments": []},
    ]
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out, scrub=scrub)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["body"] == "Hey Thomas, look at this"
    assert "Ugo" not in row["body"]


def test_build_msg_index_scrubs_quote_field(tmp_data_dir):
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "réponse", "quote": "Ugo a écrit ça", "reactions": [], "attachments": []},
    ]
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out, scrub=scrub)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["quote"] == "Thomas a écrit ça"


def test_build_msg_index_scrubber_default_is_identity(tmp_data_dir):
    """Without a scrubber, body is passed through unchanged (back-compat)."""
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "Hey Ugo", "quote": "", "reactions": [], "attachments": []},
    ]
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out)  # no scrub kwarg
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["body"] == "Hey Ugo"


def test_build_msg_index_char_count_uses_scrubbed_length(tmp_data_dir):
    """char_count must reflect the post-scrub body, not the original."""
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "Ugo", "quote": "", "reactions": [], "attachments": []},
    ]
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out, scrub=scrub)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["char_count"] == len("Thomas")


def test_build_msg_index_scrubs_reactions_sender(tmp_data_dir):
    """Reactions store the reactor's contact name; that name must also be scrubbed."""
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "hi", "quote": "",
         "reactions": [["Ugo", "👍"], ["SébastienBéal", "❤️"]],
         "attachments": []},
    ]
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out, scrub=scrub)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    # Operator's reaction is scrubbed; the other party's reaction is unchanged.
    assert row["reactions"] == [["Thomas", "👍"], ["SébastienBéal", "❤️"]]


def test_build_msg_index_handles_malformed_reactions_gracefully(tmp_data_dir):
    """Defensive: malformed reaction entries don't crash the scrubber."""
    messages = [
        {"date": "2026-05-05T13:18:00.000000", "sender": "Friend",
         "body": "hi", "quote": "",
         "reactions": [[], [None, "👍"], ["", "❤️"], ["Ugo", "👍"]],
         "attachments": []},
    ]
    scrub = compile_scrubber(["Ugo"], "Thomas Martin")
    out = tmp_data_dir / "msg_index.jsonl"
    build_msg_index(messages, out, scrub=scrub)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    # Malformed entries pass through; the one well-formed Ugo gets scrubbed.
    assert ["Thomas", "👍"] in row["reactions"]
    assert [None, "👍"] in row["reactions"]

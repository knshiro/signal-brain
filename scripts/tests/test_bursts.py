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


def test_burst_content_hash_changes_when_taxonomy_hash_changes():
    burst = {"msg_ids": ["a::Me"]}
    messages = [{"msg_id": "a::Me", "body": "hi", "reactions": []}]
    h_empty = burst_content_hash(burst, messages)
    h_with_tax = burst_content_hash(burst, messages, taxonomy_hash="sha1:tax-v1")
    h_with_tax2 = burst_content_hash(burst, messages, taxonomy_hash="sha1:tax-v2")
    assert h_empty != h_with_tax
    assert h_with_tax != h_with_tax2


def test_burst_content_hash_default_taxonomy_hash_is_empty_string():
    """Without an explicit taxonomy_hash, behaviour matches a literal "" suffix.

    This locks in the back-compat shape: callers that don't pass taxonomy_hash
    see the same value as callers passing "".
    """
    burst = {"msg_ids": ["a::Me"]}
    messages = [{"msg_id": "a::Me", "body": "hi", "reactions": []}]
    assert burst_content_hash(burst, messages) == burst_content_hash(
        burst, messages, taxonomy_hash=""
    )

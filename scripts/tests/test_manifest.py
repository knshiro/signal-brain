import json as _json
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


def test_load_or_init_handles_corrupt_file(tmp_data_dir):
    path = tmp_data_dir / "manifest.json"
    path.write_text("not json{{{", encoding="utf-8")
    m = Manifest.load_or_init(path, burst_threshold_min=60)
    assert m.content_hashes == {}


def test_load_or_init_handles_schema_mismatch(tmp_data_dir):
    path = tmp_data_dir / "manifest.json"
    path.write_text(_json.dumps({"schema_version": 999, "content_hashes": {"B0001": "x"}}),
                    encoding="utf-8")
    m = Manifest.load_or_init(path, burst_threshold_min=60)
    assert m.content_hashes == {}


def test_load_or_init_drops_unknown_fields(tmp_data_dir):
    path = tmp_data_dir / "manifest.json"
    path.write_text(_json.dumps({"schema_version": 1, "future_field": "x"}), encoding="utf-8")
    m = Manifest.load_or_init(path, burst_threshold_min=60)
    assert m.burst_threshold_min == 60

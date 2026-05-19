import json
from pathlib import Path
from signal_brain.ingest import diff_messages, run_ingest_data_layer


def test_diff_messages_identifies_new_and_modified(tmp_data_dir):
    # Existing index
    existing = [
        {"msg_id": "2026-05-05T13:00:00::Me", "date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi", "quote":"", "reactions":[], "attachments":[], "char_count":2},
    ]
    (tmp_data_dir / "msg_index.jsonl").write_text(
        "\n".join(json.dumps(r) for r in existing) + "\n", encoding="utf-8"
    )
    # New input with one identical, one new
    new_input = [
        {"date": "2026-05-05T13:00:00", "sender": "Me", "body": "hi", "quote":"", "reactions":[], "attachments":[]},
        {"date": "2026-05-05T13:05:00", "sender": "Friend", "body": "yo", "quote":"", "reactions":[], "attachments":[]},
    ]
    diff = diff_messages(new_input, tmp_data_dir / "msg_index.jsonl")
    assert len(diff["new"]) == 1
    assert diff["new"][0]["sender"] == "Friend"
    assert len(diff["modified"]) == 0


def test_run_ingest_data_layer_writes_all_artifacts(tmp_path, mini_messages, mocker):
    src = tmp_path / "out" / "Friend"
    src.mkdir(parents=True)
    (src / "data.json").write_text("\n".join(json.dumps(m) for m in mini_messages) + "\n", encoding="utf-8")
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

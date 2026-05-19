import json
from signal_brain.tagging import (
    tag_bursts, _render_burst_for_tagging,
    build_system_prompt, build_user_prompt,
)


def test_render_burst_includes_messages():
    burst = {"id": "B0001", "msg_ids": ["a::Me"]}
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "Hello there",
             "date": "2026-05-05T13:00:00"}]
    text = _render_burst_for_tagging(burst, msgs)
    assert "Me:" in text
    assert "Hello there" in text


def test_tag_bursts_reuses_cache_when_hash_unchanged(tmp_data_dir, mocker):
    bursts = [{"id": "B0001", "msg_ids": ["a::Me"], "start": "2026-05-05T13:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi", "date": "2026-05-05T13:00:00"}]
    mock_llm = mocker.MagicMock()
    cache = {"B0001": {"hash": "sha1:cached", "topics": ["banter"],
                       "primary": "banter", "summary": "cached"}}
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:cached")
    out = tmp_data_dir / "chunks.jsonl"
    tag_bursts(bursts, msgs, mock_llm, cache_by_id=cache, out_path=out)
    mock_llm.complete_json.assert_not_called()
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["primary"] == "banter"


def test_tag_bursts_calls_llm_on_cache_miss(tmp_data_dir, mocker):
    bursts = [{"id": "B0002", "msg_ids": ["a::Me"], "start": "2026-05-05T14:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "Talking about X",
             "date": "2026-05-05T14:00:00"}]
    mock_llm = mocker.MagicMock()
    mock_llm.complete_json.return_value = {
        "topics": ["topic-x"], "primary": "topic-x", "summary": "Discusses X.",
    }
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:new")
    out = tmp_data_dir / "chunks.jsonl"
    tag_bursts(bursts, msgs, mock_llm, cache_by_id={}, out_path=out)
    assert mock_llm.complete_json.call_count == 1
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["primary"] == "topic-x"


def test_system_prompt_neutral_by_default():
    prompt = build_system_prompt()
    assert "Signal conversation between two people" in prompt
    assert "French" not in prompt
    assert "politics" not in prompt


def test_system_prompt_includes_description_when_given():
    prompt = build_system_prompt("two friends debating economics")
    assert "Context: two friends debating economics" in prompt


def test_user_prompt_omits_seed_section_when_empty():
    prompt = build_user_prompt("B0001", "2026-05-05T13:00", "Me: hi", seed_tags=None)
    assert "Seed tags" not in prompt
    prompt2 = build_user_prompt("B0001", "2026-05-05T13:00", "Me: hi", seed_tags=[])
    assert "Seed tags" not in prompt2


def test_user_prompt_includes_seed_tags_when_provided():
    prompt = build_user_prompt("B0001", "2026-05-05T13:00", "Me: hi",
                                seed_tags=["topic-a", "topic-b"])
    assert "Seed tags" in prompt
    assert "topic-a" in prompt
    assert "topic-b" in prompt


def test_tag_bursts_forwards_description_and_seed_tags_to_prompt(tmp_data_dir, mocker):
    """When called with hints, they should reach the LLM via the prompts."""
    bursts = [{"id": "B0001", "msg_ids": ["a::Me"], "start": "2026-05-05T13:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi", "date": "2026-05-05T13:00:00"}]
    mock_llm = mocker.MagicMock()
    mock_llm.complete_json.return_value = {"topics": ["t"], "primary": "t", "summary": "s"}
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:new")
    tag_bursts(bursts, msgs, mock_llm, cache_by_id={}, out_path=tmp_data_dir / "chunks.jsonl",
               description="two friends talking shop", seed_tags=["work", "life"])
    call = mock_llm.complete_json.call_args
    system, user = call.args[0], call.args[1]
    assert "Context: two friends talking shop" in system
    assert "Seed tags" in user
    assert "work" in user
    assert "life" in user

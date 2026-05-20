"""Tests for the tagging plan/finalize phases.

The tagger no longer calls an LLM directly. `emit_tagging_todos` writes a
todo file; `finalize_tagging` reads a done file (the agent provides) and
writes chunks.jsonl.
"""
import json
from signal_brain.tagging import (
    build_system_prompt,
    build_user_prompt,
    emit_tagging_todos,
    finalize_tagging,
    _render_burst_for_tagging,
)
from signal_brain.worklist import load_todo


def test_render_burst_includes_messages():
    burst = {"id": "B0001", "msg_ids": ["a::Me"]}
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "Hello there",
             "date": "2026-05-05T13:00:00"}]
    text = _render_burst_for_tagging(burst, msgs)
    assert "Me:" in text
    assert "Hello there" in text


def test_emit_tagging_todos_skips_cache_hits(tmp_path, mocker):
    bursts = [{"id": "B0001", "msg_ids": ["a::Me"], "start": "2026-05-05T13:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi", "date": "2026-05-05T13:00:00"}]
    cache = {"B0001": {"hash": "sha1:cached", "topics": ["banter"],
                       "primary": "banter", "summary": "cached"}}
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:cached")
    todo = tmp_path / "tagging.todo.jsonl"
    hashes = emit_tagging_todos(bursts, msgs, cache, todo)
    assert hashes == {"B0001": "sha1:cached"}
    assert load_todo(todo) == []  # cache hit, nothing to do


def test_emit_tagging_todos_emits_when_cache_miss(tmp_path, mocker):
    bursts = [{"id": "B0002", "msg_ids": ["a::Me"], "start": "2026-05-05T14:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "Talking about X",
             "date": "2026-05-05T14:00:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:new")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, cache_by_id={}, todo_path=todo)
    rows = load_todo(todo)
    assert len(rows) == 1
    assert rows[0]["stage"] == "tagging"
    assert rows[0]["kind"] == "burst"
    assert rows[0]["context"]["burst_id"] == "B0002"
    assert "Talking about X" in rows[0]["user_prompt"]


def test_emit_is_idempotent_under_replan(tmp_path, mocker):
    """Re-running plan with no content changes must not duplicate rows."""
    bursts = [{"id": "B0003", "msg_ids": ["a::Me"], "start": "2026-05-05T15:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi",
             "date": "2026-05-05T15:00:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:new")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, {}, todo)
    emit_tagging_todos(bursts, msgs, {}, todo)
    assert len(load_todo(todo)) == 1


def test_finalize_tagging_consumes_done_rows(tmp_path, mocker):
    bursts = [{"id": "B0010", "msg_ids": ["a::Me"], "start": "2026-05-05T16:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "Let's talk Y",
             "date": "2026-05-05T16:00:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:y")

    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, {}, todo)
    todo_row = load_todo(todo)[0]
    done = tmp_path / "tagging.done.jsonl"
    done.write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {"topics": ["topic-y"], "primary": "topic-y",
                     "summary": "Discusses Y.", "out_of_taxonomy": False},
    }) + "\n", encoding="utf-8")

    chunks = tmp_path / "chunks.jsonl"
    stats = finalize_tagging(bursts, {}, todo, done, chunks)
    assert stats["new"] == 1
    assert stats["cached"] == 0
    assert stats["missing"] == []
    row = json.loads(chunks.read_text(encoding="utf-8").splitlines()[0])
    assert row["primary"] == "topic-y"


def test_finalize_tagging_reuses_cache_when_no_todo(tmp_path, mocker):
    """A burst whose hash matches the cache yields a chunks row from cache, no todo."""
    bursts = [{"id": "B0020", "msg_ids": ["a::Me"], "start": "2026-05-05T17:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi",
             "date": "2026-05-05T17:00:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:cached")
    cache = {"B0020": {"hash": "sha1:cached", "topics": ["banter"],
                       "primary": "banter", "summary": "cached row"}}

    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, cache, todo)  # cache hit, no todo emitted
    done = tmp_path / "tagging.done.jsonl"
    chunks = tmp_path / "chunks.jsonl"
    stats = finalize_tagging(bursts, cache, todo, done, chunks)
    assert stats["new"] == 0
    assert stats["cached"] == 1
    row = json.loads(chunks.read_text(encoding="utf-8").splitlines()[0])
    assert row["summary"] == "cached row"


def test_finalize_tagging_reports_missing_when_done_absent(tmp_path, mocker):
    bursts = [{"id": "B0030", "msg_ids": ["a::Me"], "start": "2026-05-05T18:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi",
             "date": "2026-05-05T18:00:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:miss")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, {}, todo)
    done = tmp_path / "tagging.done.jsonl"  # never created
    chunks = tmp_path / "chunks.jsonl"
    stats = finalize_tagging(bursts, {}, todo, done, chunks)
    assert stats["new"] == 0
    assert stats["missing"] == ["B0030"]


def test_finalize_tagging_reports_invalid_schema(tmp_path, mocker):
    bursts = [{"id": "B0040", "msg_ids": ["a::Me"], "start": "2026-05-05T19:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi",
             "date": "2026-05-05T19:00:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:bad")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, {}, todo)
    todo_row = load_todo(todo)[0]
    done = tmp_path / "tagging.done.jsonl"
    done.write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {"primary": "x"},  # missing topics and summary
    }) + "\n", encoding="utf-8")
    chunks = tmp_path / "chunks.jsonl"
    stats = finalize_tagging(bursts, {}, todo, done, chunks)
    assert stats["invalid"] == ["B0040"]
    assert chunks.read_text(encoding="utf-8") == ""  # no rows written


def test_system_prompt_neutral_by_default():
    prompt = build_system_prompt()
    assert "Signal conversation between two people" in prompt
    assert "Context:" not in prompt


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


def test_emit_forwards_description_and_seed_tags_into_prompts(tmp_path, mocker):
    bursts = [{"id": "B0050", "msg_ids": ["a::Me"], "start": "2026-05-05T20:00:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi",
             "date": "2026-05-05T20:00:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:n")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, {}, todo,
                       description="two friends talking shop",
                       seed_tags=["work", "life"])
    row = load_todo(todo)[0]
    assert "Context: two friends talking shop" in row["system_prompt"]
    assert "Seed tags" in row["user_prompt"]
    assert "work" in row["user_prompt"]


def test_system_prompt_includes_required_vocabulary_when_taxonomy_provided():
    prompt = build_system_prompt(required_taxonomy=["wealth", "media"])
    assert "controlled vocabulary" in prompt.lower() or "required vocabulary" in prompt.lower()
    assert "out_of_taxonomy" in prompt


def test_system_prompt_neutral_when_no_taxonomy():
    prompt = build_system_prompt()
    assert "controlled vocabulary" not in prompt.lower()
    assert "out_of_taxonomy" not in prompt


def test_user_prompt_includes_required_vocabulary_section():
    prompt = build_user_prompt(
        "B0001", "2026-05-05T13:00", "Me: hi",
        seed_tags=None,
        required_taxonomy=["wealth-concentration", "media-criticism"],
    )
    assert "Required vocabulary" in prompt
    assert "wealth-concentration" in prompt
    assert "media-criticism" in prompt


def test_user_prompt_required_taxonomy_takes_precedence_over_seed_tags():
    """When both are set, the required-vocabulary framing wins; soft seed_tags suppressed."""
    prompt = build_user_prompt(
        "B0001", "2026-05-05T13:00", "Me: hi",
        seed_tags=["soft-a"],
        required_taxonomy=["hard-b"],
    )
    assert "Required vocabulary" in prompt
    assert "hard-b" in prompt
    assert "Seed tags" not in prompt


def test_tagging_schema_includes_out_of_taxonomy():
    from signal_brain.tagging import TAGGING_RESPONSE_SCHEMA
    assert "out_of_taxonomy" in TAGGING_RESPONSE_SCHEMA["required"]
    assert TAGGING_RESPONSE_SCHEMA["types"]["out_of_taxonomy"] == "bool"


def test_emit_tagging_todos_threads_taxonomy_into_prompt(tmp_path, mocker):
    bursts = [{"id": "B0100", "msg_ids": ["a::Me"], "start": "2026-05-05T13:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "discutons",
             "date": "2026-05-05T13:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:n")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(
        bursts, msgs, {}, todo,
        required_taxonomy=["wealth-concentration", "media-criticism"],
    )
    row = load_todo(todo)[0]
    assert "Required vocabulary" in row["user_prompt"]
    assert "wealth-concentration" in row["user_prompt"]
    assert "out_of_taxonomy" in row["system_prompt"]


def test_finalize_tagging_propagates_out_of_taxonomy_to_chunks(tmp_path, mocker):
    bursts = [{"id": "B0200", "msg_ids": ["a::Me"], "start": "2026-05-05T14:00"}]
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "hi",
             "date": "2026-05-05T14:00"}]
    mocker.patch("signal_brain.tagging.burst_content_hash", return_value="sha1:n")
    todo = tmp_path / "tagging.todo.jsonl"
    emit_tagging_todos(bursts, msgs, {}, todo,
                       required_taxonomy=["wealth-concentration"])
    todo_row = load_todo(todo)[0]
    done = tmp_path / "tagging.done.jsonl"
    done.write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {
            "topics": ["wealth-concentration"],
            "primary": "wealth-concentration",
            "summary": "About money.",
            "out_of_taxonomy": False,
        },
    }) + "\n", encoding="utf-8")
    chunks = tmp_path / "chunks.jsonl"
    finalize_tagging(bursts, {}, todo, done, chunks)
    row = json.loads(chunks.read_text(encoding="utf-8").splitlines()[0])
    assert row["out_of_taxonomy"] is False

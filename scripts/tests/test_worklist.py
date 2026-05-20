"""Tests for the plan/finalize worklist contract."""
import json
import pytest
from signal_brain.worklist import (
    WorklistError,
    emit,
    load_done,
    load_todo,
    parse_subagent_response,
    stable_job_id,
    validate_response,
)


def test_job_id_is_stable_across_calls():
    a = stable_job_id("tagging", "burst", "sys", "user")
    b = stable_job_id("tagging", "burst", "sys", "user")
    assert a == b
    assert len(a) == 16


def test_job_id_changes_when_any_input_changes():
    base = stable_job_id("tagging", "burst", "s", "u")
    assert base != stable_job_id("synthesis", "burst", "s", "u")
    assert base != stable_job_id("tagging", "page", "s", "u")
    assert base != stable_job_id("tagging", "burst", "s2", "u")
    assert base != stable_job_id("tagging", "burst", "s", "u2")


def test_emit_appends_one_row(tmp_path):
    todo = tmp_path / "todo.jsonl"
    jid = emit(todo, stage="tagging", kind="burst",
               system="s", user="u",
               response_schema={"required": ["x"]}, context={"burst_id": "B0001"})
    rows = load_todo(todo)
    assert len(rows) == 1
    assert rows[0]["job_id"] == jid
    assert rows[0]["stage"] == "tagging"
    assert rows[0]["context"]["burst_id"] == "B0001"


def test_emit_is_idempotent_by_job_id(tmp_path):
    todo = tmp_path / "todo.jsonl"
    emit(todo, stage="tagging", kind="burst", system="s", user="u",
         response_schema={}, context={})
    emit(todo, stage="tagging", kind="burst", system="s", user="u",
         response_schema={}, context={})
    assert len(load_todo(todo)) == 1


def test_emit_preserves_unicode_round_trip(tmp_path):
    todo = tmp_path / "todo.jsonl"
    emit(todo, stage="tagging", kind="burst", system="Élu",
         user="Amélie: hi", response_schema={}, context={})
    raw = todo.read_text(encoding="utf-8")
    assert "Amélie" in raw
    assert "Élu" in raw


def test_load_done_returns_empty_when_file_missing(tmp_path):
    assert load_done(tmp_path / "nope.jsonl") == {}


def test_load_done_last_row_wins_for_duplicate_job_id(tmp_path):
    done = tmp_path / "done.jsonl"
    rows = [
        {"job_id": "x1", "response": {"v": 1}},
        {"job_id": "x1", "response": {"v": 2}},
    ]
    done.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    loaded = load_done(done)
    assert loaded["x1"]["response"]["v"] == 2


def test_validate_response_accepts_valid():
    schema = {"required": ["topics", "primary"],
              "types": {"topics": "list", "primary": "str"}}
    validate_response({"topics": ["a"], "primary": "a"}, schema)


def test_validate_response_rejects_missing_key():
    schema = {"required": ["topics"]}
    with pytest.raises(WorklistError, match="Missing required key"):
        validate_response({"primary": "x"}, schema)


def test_validate_response_rejects_wrong_type():
    schema = {"required": ["topics"], "types": {"topics": "list"}}
    with pytest.raises(WorklistError, match="expected list"):
        validate_response({"topics": "not-a-list"}, schema)


def test_validate_response_rejects_non_dict():
    with pytest.raises(WorklistError, match="must be a JSON object"):
        validate_response([1, 2, 3], {"required": []})


def test_parse_subagent_response_handles_plain_json():
    assert parse_subagent_response('{"a": 1}') == {"a": 1}


def test_parse_subagent_response_strips_json_fence():
    text = '```json\n{"a": 1}\n```'
    assert parse_subagent_response(text) == {"a": 1}


def test_parse_subagent_response_strips_bare_fence():
    text = '```\n{"a": 1}\n```'
    assert parse_subagent_response(text) == {"a": 1}


def test_parse_subagent_response_raises_on_malformed():
    with pytest.raises(WorklistError, match="not valid JSON"):
        parse_subagent_response("not json at all")


def test_parse_subagent_response_raises_on_non_object():
    with pytest.raises(WorklistError, match="must be a JSON object"):
        parse_subagent_response("[1, 2, 3]")

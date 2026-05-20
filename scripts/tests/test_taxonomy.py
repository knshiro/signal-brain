"""Tests for the taxonomy stage (plan/finalize worklist contract)."""
import json
from pathlib import Path

from signal_brain.taxonomy import (
    TAXONOMY_RESPONSE_SCHEMA,
    build_system_prompt,
    build_user_prompt,
    emit_taxonomy_todo,
    finalize_taxonomy,
    load_taxonomy_cache,
    source_content_hash,
)
from signal_brain.worklist import load_todo


def test_source_content_hash_stable_across_calls():
    msgs = [
        {"msg_id": "a::Me", "body": "hello", "reactions": []},
        {"msg_id": "b::Friend", "body": "salut", "reactions": []},
    ]
    h1 = source_content_hash(msgs)
    h2 = source_content_hash(msgs)
    assert h1 == h2
    assert h1.startswith("sha1:")


def test_source_content_hash_changes_when_body_changes():
    base = [{"msg_id": "a::Me", "body": "hello", "reactions": []}]
    modified = [{"msg_id": "a::Me", "body": "HELLO", "reactions": []}]
    assert source_content_hash(base) != source_content_hash(modified)


def test_source_content_hash_changes_when_message_added():
    base = [{"msg_id": "a::Me", "body": "x", "reactions": []}]
    extended = base + [{"msg_id": "b::Me", "body": "y", "reactions": []}]
    assert source_content_hash(base) != source_content_hash(extended)


def test_taxonomy_schema_shape():
    assert TAXONOMY_RESPONSE_SCHEMA["required"] == ["taxonomy", "notes"]
    assert TAXONOMY_RESPONSE_SCHEMA["types"]["taxonomy"] == "list"
    assert TAXONOMY_RESPONSE_SCHEMA["types"]["notes"] == "str"


def test_system_prompt_mentions_canonical_vocabulary():
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "vocabulary" in lower or "taxonomy" in lower
    assert "slug" in lower


def test_user_prompt_embeds_conversation_text():
    text = "Me: hi\nFriend: hello"
    prompt = build_user_prompt(text)
    assert "Me: hi" in prompt
    assert "Friend: hello" in prompt


def test_emit_taxonomy_todo_writes_one_row(tmp_path):
    msgs = [
        {"msg_id": "a::Me", "sender": "Me", "body": "discutons capital",
         "reactions": []},
        {"msg_id": "b::Friend", "sender": "Friend", "body": "ok parlons",
         "reactions": []},
    ]
    todo = tmp_path / "taxonomy.todo.jsonl"
    job_id = emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    assert job_id is not None
    rows = load_todo(todo)
    assert len(rows) == 1
    assert rows[0]["stage"] == "taxonomy"
    assert rows[0]["kind"] == "source"
    assert rows[0]["context"]["source_hash"] == "sha1:abc"
    assert "discutons capital" in rows[0]["user_prompt"]


def test_emit_taxonomy_todo_is_idempotent_on_replan(tmp_path):
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "x", "reactions": []}]
    todo = tmp_path / "taxonomy.todo.jsonl"
    emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    assert len(load_todo(todo)) == 1


def test_finalize_taxonomy_writes_cache(tmp_path):
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "x", "reactions": []}]
    todo = tmp_path / "taxonomy.todo.jsonl"
    emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    todo_row = load_todo(todo)[0]
    done = tmp_path / "taxonomy.done.jsonl"
    done.write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {"taxonomy": ["wealth-concentration", "media-criticism"],
                     "notes": "two themes"},
    }) + "\n", encoding="utf-8")
    cache = tmp_path / "taxonomy.json"
    result = finalize_taxonomy(todo, done, cache, source_hash="sha1:abc")
    assert result["taxonomy"] == ["wealth-concentration", "media-criticism"]
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["source_hash"] == "sha1:abc"
    assert data["taxonomy"] == ["wealth-concentration", "media-criticism"]
    assert data["notes"] == "two themes"


def test_load_taxonomy_cache_hit(tmp_path):
    cache = tmp_path / "taxonomy.json"
    cache.write_text(json.dumps({
        "source_hash": "sha1:abc",
        "taxonomy": ["a", "b"],
        "notes": "",
    }), encoding="utf-8")
    result = load_taxonomy_cache(cache, source_hash="sha1:abc")
    assert result == ["a", "b"]


def test_load_taxonomy_cache_miss_on_hash_mismatch(tmp_path):
    cache = tmp_path / "taxonomy.json"
    cache.write_text(json.dumps({
        "source_hash": "sha1:old",
        "taxonomy": ["a"],
        "notes": "",
    }), encoding="utf-8")
    assert load_taxonomy_cache(cache, source_hash="sha1:new") is None


def test_load_taxonomy_cache_missing_file_returns_none(tmp_path):
    assert load_taxonomy_cache(tmp_path / "nope.json", source_hash="sha1:abc") is None


def test_finalize_taxonomy_rejects_empty_taxonomy(tmp_path):
    """An empty taxonomy list is malformed input — treated as still-pending."""
    msgs = [{"msg_id": "a::Me", "sender": "Me", "body": "x", "reactions": []}]
    todo = tmp_path / "taxonomy.todo.jsonl"
    emit_taxonomy_todo(msgs, todo, description="", source_hash="sha1:abc")
    todo_row = load_todo(todo)[0]
    done = tmp_path / "taxonomy.done.jsonl"
    done.write_text(json.dumps({
        "job_id": todo_row["job_id"],
        "response": {"taxonomy": [], "notes": "empty"},
    }) + "\n", encoding="utf-8")
    cache = tmp_path / "taxonomy.json"
    result = finalize_taxonomy(todo, done, cache, source_hash="sha1:abc")
    assert result is None
    assert not cache.exists()  # no cache written for an empty taxonomy


def test_load_taxonomy_cache_rejects_empty_taxonomy(tmp_path):
    """A cached empty taxonomy is not a usable cache."""
    cache = tmp_path / "taxonomy.json"
    cache.write_text(json.dumps({
        "source_hash": "sha1:abc",
        "taxonomy": [],
        "notes": "",
    }), encoding="utf-8")
    assert load_taxonomy_cache(cache, source_hash="sha1:abc") is None

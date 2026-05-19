import pytest
from signal_brain.sources import (
    slugify, list_sources, resolve_source,
    AmbiguousSource, NoSourceFound,
)


def test_slugify_strips_diacritics():
    assert slugify("RenéMüller") == "renemuller"


def test_slugify_handles_spaces_and_punctuation():
    assert slugify("Marie-Claire D'Avignon") == "marie-claire-d-avignon"


def test_slugify_lowercases():
    assert slugify("Me") == "me"


def test_slugify_empty_input():
    assert slugify("") == ""


def test_slugify_only_diacritics():
    # All chars stripped → empty
    assert slugify("éé") == "ee"


def test_list_sources_returns_sorted_dirs_with_data_json(tmp_path):
    (tmp_path / "Alice").mkdir()
    (tmp_path / "Alice" / "data.json").write_text("[]", encoding="utf-8")
    (tmp_path / "Bob").mkdir()
    (tmp_path / "Bob" / "data.json").write_text("[]", encoding="utf-8")
    (tmp_path / "NoData").mkdir()  # no data.json — should be excluded
    assert list_sources(tmp_path) == ["Alice", "Bob"]


def test_list_sources_returns_empty_when_out_missing(tmp_path):
    assert list_sources(tmp_path / "missing") == []


def test_resolve_source_auto_picks_when_one(tmp_path):
    (tmp_path / "Alice").mkdir()
    (tmp_path / "Alice" / "data.json").write_text("[]", encoding="utf-8")
    assert resolve_source(None, tmp_path) == "Alice"


def test_resolve_source_ambiguous_when_multiple(tmp_path):
    (tmp_path / "Alice").mkdir()
    (tmp_path / "Alice" / "data.json").write_text("[]", encoding="utf-8")
    (tmp_path / "Bob").mkdir()
    (tmp_path / "Bob" / "data.json").write_text("[]", encoding="utf-8")
    with pytest.raises(AmbiguousSource):
        resolve_source(None, tmp_path)


def test_resolve_source_no_sources_raises(tmp_path):
    with pytest.raises(NoSourceFound):
        resolve_source(None, tmp_path)


def test_resolve_source_named_must_exist(tmp_path):
    (tmp_path / "Alice").mkdir()
    (tmp_path / "Alice" / "data.json").write_text("[]", encoding="utf-8")
    assert resolve_source("Alice", tmp_path) == "Alice"
    with pytest.raises(NoSourceFound):
        resolve_source("Bob", tmp_path)

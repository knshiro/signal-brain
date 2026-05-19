"""Shared test fixtures."""
import json
from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mini_messages():
    """50-message slice of the Signal thread for integration tests."""
    path = FIXTURE_DIR / "mini_data.json"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def tmp_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def tmp_wiki_dir(tmp_path):
    d = tmp_path / "wiki"
    for sub in ["people", "concepts", "positions", "arcs", "cross"]:
        (d / sub).mkdir(parents=True)
    return d

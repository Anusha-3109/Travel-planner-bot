import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

TEST_CITIES = ["Myrtle Beach", "Rockford"]


@pytest.fixture(autouse=True)
def no_live_calls(tmp_path, monkeypatch):
    """Tests never use real API keys, quota or the shared cache. Tests that cover
    live data set a fake key and mock the network themselves."""
    monkeypatch.setattr(config, "SERPAPI_API_KEY", "")
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "")
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "live-cache.sqlite3")
    # A fresh per-chat live search budget, so mocked searches in earlier tests don't use it up.
    from live import budget
    monkeypatch.setattr(budget, "_default", budget.SessionBudget())


@pytest.fixture(scope="session")
def small_index(tmp_path_factory):
    """A throwaway Chroma index with two cities, so tests don't need the full ~13,700-place index."""
    from rag import vectorstore
    from rag.ingest import build_index

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "CHROMA_DIR", tmp_path_factory.mktemp("chroma"))
        vectorstore._client.cache_clear()
        yield build_index(cities=TEST_CITIES)
    vectorstore._client.cache_clear()

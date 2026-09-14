import pytest

from grscraper import config


@pytest.fixture(autouse=True)
def isolated_browser_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_PROFILE", tmp_path / "browser_profile")

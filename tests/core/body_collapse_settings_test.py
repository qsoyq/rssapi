from pathlib import Path

import pytest

from rssapi.core.settings import AppSettings


def test_body_collapse_defaults_to_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RSS_COLLAPSE_BODY_ENABLED", raising=False)

    assert AppSettings().rss_collapse_body_enabled is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("false", False), ("t", True), ("f", False), ("1", True), ("0", False)],
)
def test_body_collapse_environment_override(
    value: str, expected: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RSS_COLLAPSE_BODY_ENABLED", value)

    assert AppSettings().rss_collapse_body_enabled is expected


def test_body_collapse_dotenv_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RSS_COLLAPSE_BODY_ENABLED", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("RSS_COLLAPSE_BODY_ENABLED=false\n", encoding="utf-8")

    assert AppSettings().rss_collapse_body_enabled is False

"""Configuration tests."""

from app.core.config import get_settings


def test_default_settings_are_loaded() -> None:
    settings = get_settings()

    assert settings.app_name == "NetTwin AI"
    assert settings.gns3_server_url == "http://localhost:3080"
    assert settings.gns3_request_timeout > 0


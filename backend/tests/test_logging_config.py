from agentos.logging_config import get_log_access, get_log_level


def test_log_level_defaults_to_info(monkeypatch):
    monkeypatch.delenv("AGENTOS_LOG_LEVEL", raising=False)
    assert get_log_level() == "info"


def test_invalid_log_level_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("AGENTOS_LOG_LEVEL", "loud")
    assert get_log_level() == "info"


def test_log_access_accepts_common_boolean_values(monkeypatch):
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv("AGENTOS_LOG_ACCESS", value)
        assert get_log_access() is True

    monkeypatch.setenv("AGENTOS_LOG_ACCESS", "false")
    assert get_log_access() is False

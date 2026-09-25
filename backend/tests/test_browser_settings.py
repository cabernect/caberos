"""Browser settings API + persisted override overlay (W4).

Seam under test: /api/settings/browser endpoints, persist_setting(), and
_apply_persisted_overrides() precedence — env/.env pins always win over the
UI-saved value. Tests observe HTTP responses and the JSON file, never
internals.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.db import get_db
from agentos.main import app


@pytest.fixture
async def client(db):
    from agentos.auth import require_operator
    from agentos.models.operator import Operator

    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def settings_overlay(tmp_path, monkeypatch):
    """Redirect the persisted overlay + live browser_binary to throwaway state.

    The dev .env pins AGENTOS_BROWSER_BINARY on some machines — neutralize
    both the env var (find_browser_binary reads os.environ directly) and
    env_pinned so tests exercise the persisted path deterministically.
    """
    import agentos.config as config

    monkeypatch.delenv("AGENTOS_BROWSER_BINARY", raising=False)
    monkeypatch.setattr(config.settings, "db_path", tmp_path / "agentos.db")
    monkeypatch.setattr(config.settings, "browser_binary", "")
    monkeypatch.setattr(config, "env_pinned", lambda key: False)
    return tmp_path


async def test_get_browser_settings_shape(client, settings_overlay):
    resp = await client.get("/api/settings/browser")
    assert resp.status_code == 200
    data = resp.json()
    assert data["binary_override"] == ""
    assert data["override_source"] == "none"
    assert "runtime" in data and "status" in data["runtime"]


async def test_put_rejects_missing_file(client, settings_overlay):
    resp = await client.put("/api/settings/browser", json={"binary_override": "/no/such/binary"})
    assert resp.status_code == 422
    assert "not a file" in resp.json()["detail"]


async def test_put_persists_and_get_reads_back(client, settings_overlay):
    fake_bin = settings_overlay / "fake-chrome"
    fake_bin.write_text("#!/bin/sh\n")

    resp = await client.put("/api/settings/browser", json={"binary_override": str(fake_bin)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["binary_override"] == str(fake_bin)
    assert data["override_source"] == "persisted"
    assert data["resolved_binary"] == str(fake_bin)
    assert data["runtime"]["status"] == "ok"
    assert data["runtime"]["managed"] is False

    saved = json.loads((settings_overlay / "app-settings.json").read_text())
    assert saved["browser_binary"] == str(fake_bin)

    resp = await client.get("/api/settings/browser")
    assert resp.json()["binary_override"] == str(fake_bin)


async def test_put_empty_clears_override(client, settings_overlay):
    fake_bin = settings_overlay / "fake-chrome"
    fake_bin.write_text("#!/bin/sh\n")
    await client.put("/api/settings/browser", json={"binary_override": str(fake_bin)})

    resp = await client.put("/api/settings/browser", json={"binary_override": ""})
    assert resp.status_code == 200
    assert resp.json()["binary_override"] == ""
    assert resp.json()["override_source"] == "none"
    saved = json.loads((settings_overlay / "app-settings.json").read_text())
    assert "browser_binary" not in saved


async def test_put_refused_when_env_pinned(client, settings_overlay, monkeypatch):
    import agentos.config as config

    monkeypatch.setattr(config, "env_pinned", lambda key: True)
    resp = await client.put("/api/settings/browser", json={"binary_override": "/tmp/x"})
    assert resp.status_code == 409
    assert "AGENTOS_BROWSER_BINARY" in resp.json()["detail"]

    resp = await client.get("/api/settings/browser")
    assert resp.json()["override_source"] == "env"


class TestEnvPinned:
    def test_env_var(self, monkeypatch):
        from agentos.config import env_pinned

        monkeypatch.setenv("AGENTOS_BROWSER_BINARY", "/x")
        assert env_pinned("browser_binary") is True

    def test_env_file(self, tmp_path, monkeypatch):
        from agentos.config import env_pinned

        monkeypatch.delenv("AGENTOS_BROWSER_BINARY", raising=False)
        (tmp_path / ".env").write_text("AGENTOS_BROWSER_BINARY=/x\n")
        monkeypatch.chdir(tmp_path)
        assert env_pinned("browser_binary") is True

    def test_unset(self, tmp_path, monkeypatch):
        from agentos.config import env_pinned

        monkeypatch.delenv("AGENTOS_BROWSER_BINARY", raising=False)
        monkeypatch.chdir(tmp_path)  # cwd without .env
        assert env_pinned("browser_binary") is False


def test_persisted_overlay_skips_env_pinned(tmp_path, monkeypatch):
    """A stale UI-saved value must not clobber an env/.env pin on restart."""
    import agentos.config as config

    (tmp_path / "app-settings.json").write_text(json.dumps({"browser_binary": "/stale/ui-value"}))
    monkeypatch.setattr(config.settings, "db_path", tmp_path / "agentos.db")
    monkeypatch.setattr(config.settings, "browser_binary", "/env/chrome")
    monkeypatch.setattr(config, "env_pinned", lambda key: True)

    config._apply_persisted_overrides()
    assert config.settings.browser_binary == "/env/chrome"


def test_persisted_overlay_applies_when_not_pinned(tmp_path, monkeypatch):
    import agentos.config as config

    (tmp_path / "app-settings.json").write_text(json.dumps({"browser_binary": "/saved/chrome"}))
    monkeypatch.setattr(config.settings, "db_path", tmp_path / "agentos.db")
    monkeypatch.setattr(config.settings, "browser_binary", "")
    monkeypatch.setattr(config, "env_pinned", lambda key: False)

    config._apply_persisted_overrides()
    assert config.settings.browser_binary == "/saved/chrome"

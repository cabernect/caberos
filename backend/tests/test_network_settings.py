"""Network settings API — web_private_allowlist round-trip and validation.

Seam under test: /api/settings/network endpoints and the persisted overlay,
the same pattern as the browser-settings tests.
"""

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
    import agentos.config as config

    monkeypatch.setattr(config.settings, "db_path", tmp_path / "agentos.db")
    monkeypatch.setattr(config.settings, "web_private_allowlist", [])
    monkeypatch.setattr(config, "env_pinned", lambda key: False)
    return tmp_path


async def test_get_defaults(client, settings_overlay):
    resp = await client.get("/api/settings/network")
    assert resp.status_code == 200
    assert resp.json() == {"web_private_allowlist": [], "pinned": False}


async def test_put_normalizes_and_persists(client, settings_overlay):
    resp = await client.put(
        "/api/settings/network",
        json={"web_private_allowlist": ["Wiki.Internal.", "lan", " 192.168.1.5 "]},
    )
    assert resp.status_code == 200
    assert resp.json()["web_private_allowlist"] == ["wiki.internal", "lan", "192.168.1.5"]
    # Persisted overlay survived and landed in the live settings.
    overlay = (settings_overlay / "app-settings.json").read_text()
    assert "wiki.internal" in overlay

    resp = await client.get("/api/settings/network")
    assert resp.json()["web_private_allowlist"] == ["wiki.internal", "lan", "192.168.1.5"]


async def test_put_rejects_url_shaped_entries(client, settings_overlay):
    for bad in ["http://internal/", "internal/path", "host:8080", "user@host", "not a host"]:
        resp = await client.put("/api/settings/network", json={"web_private_allowlist": [bad]})
        assert resp.status_code == 422, bad
    # Nothing persisted from the rejected writes.
    resp = await client.get("/api/settings/network")
    assert resp.json()["web_private_allowlist"] == []


async def test_env_pin_blocks_ui_write(client, settings_overlay, monkeypatch):
    import agentos.api.settings as api_settings

    monkeypatch.setattr(api_settings, "env_pinned", lambda key: True)
    resp = await client.put(
        "/api/settings/network", json={"web_private_allowlist": ["wiki.internal"]}
    )
    assert resp.status_code == 409
    assert "AGENTOS_WEB_PRIVATE_ALLOWLIST" in resp.json()["detail"]


@pytest.mark.parametrize("entries", [["*.lan"], [""], ["a" * 254], ["host"] * 51])
async def test_invalid_grants_are_rejected_not_truncated(client, settings_overlay, entries):
    response = await client.put("/api/settings/network", json={"web_private_allowlist": entries})
    assert response.status_code == 422
    current = await client.get("/api/settings/network")
    assert current.json()["web_private_allowlist"] == []


async def test_rejection_does_not_echo_embedded_credentials(client, settings_overlay):
    response = await client.put(
        "/api/settings/network",
        json={"web_private_allowlist": ["http://operator:dummy-private-secret@host/"]},
    )
    assert response.status_code == 422
    assert "dummy-private-secret" not in response.text

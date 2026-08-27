import pytest
from httpx import ASGITransport, AsyncClient

from agentos.auth import require_operator
from agentos.db import get_db
from agentos.main import app
from agentos.models.operator import Operator
from agentos.notifications import create_notification


@pytest.fixture
async def client(db):
    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_notifications_are_listed_and_marked_read(client, db):
    await create_notification(
        db,
        notification_type="oauth_reauth_required",
        severity="error",
        title="Reconnect Notion",
        message="The OAuth refresh token is no longer valid.",
        action_path="/mcps",
        entity_id="server-1",
    )
    await db.commit()

    unread = await client.get("/api/notifications", params={"unread_only": True})
    assert unread.status_code == 200
    notification = unread.json()[0]
    assert notification["title"] == "Reconnect Notion"
    assert notification["read"] is False

    marked = await client.post(f"/api/notifications/{notification['id']}/read")
    assert marked.status_code == 200
    assert (await client.get("/api/notifications", params={"unread_only": True})).json() == []

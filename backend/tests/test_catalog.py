"""W11 catalog slice — bundled snapshot, offering registry, discovery."""

import asyncio
import json
import uuid

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentos.models import Base
from agentos.models.model_catalog import ModelCatalogOffering, ModelCatalogRevision
from agentos.models.provider import Provider
from agentos.providers import catalog as catalog_mod
from agentos.providers.catalog import CatalogSnapshot
from agentos.providers.model_catalog import (
    _fingerprint,
    update_override,
)
from agentos.secret_store import encrypt

pytest_asyncio_fixture = pytest_asyncio.fixture


def _tiny_catalog() -> bytes:
    return json.dumps(
        {
            "openai": {
                "models": {
                    "gpt-6": {
                        "name": "GPT-6",
                        "limit": {"context": 400000, "input": 272000, "output": 128000},
                        "modalities": {"input": ["text", "image"], "output": ["text"]},
                        "reasoning": True,
                        "status": "active",
                        "cost": {"input": 2.0, "output": 10.0},
                    }
                }
            }
        }
    ).encode()


@pytest_asyncio_fixture
async def snapshot(tmp_path):
    bundled = tmp_path / "bundled.json"
    bundled.write_bytes(_tiny_catalog())
    snap = CatalogSnapshot(store_dir=tmp_path / "store", bundled_path=bundled)
    yield snap


class TestSnapshot:
    def test_bundled_lookup_exact(self, snapshot):
        entry = snapshot.lookup("openai", "gpt-6")
        assert entry is not None and entry["limit"]["context"] == 400000

    def test_lookup_unknown_is_none_not_guessed(self, snapshot):
        assert snapshot.lookup("openai", "gpt-6-turbo") is None
        assert snapshot.lookup("ollama", "llama3") is None

    async def test_refresh_atomic_good_then_bad_retains_old(self, snapshot):
        good = json.dumps(
            {"anthropic": {"models": {"claude-4": {"name": "Claude 4", "status": "active"}}}}
        ).encode()
        result = await snapshot.refresh(fetcher=lambda: asyncio.sleep(0, good))
        assert result["ok"] and snapshot.lookup("anthropic", "claude-4")
        rev = result["revision"]

        result2 = await snapshot.refresh(fetcher=lambda: asyncio.sleep(0, b"not-json{{"))
        assert not result2["ok"]
        assert snapshot.status()["revision"] == rev
        assert snapshot.lookup("anthropic", "claude-4")

        big = b"x" * (catalog_mod.CATALOG_MAX_BYTES + 1)
        result3 = await snapshot.refresh(fetcher=lambda: asyncio.sleep(0, big))
        assert not result3["ok"] and snapshot.status()["revision"] == rev

    async def test_concurrent_refresh_deduplicates(self, snapshot):
        calls = 0

        async def fetch():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return _tiny_catalog()

        r1, r2 = await asyncio.gather(
            snapshot.refresh(fetcher=fetch), snapshot.refresh(fetcher=fetch)
        )
        assert r1["ok"] and r2["ok"] and calls == 1


def _session(factory):
    return factory()


@pytest_asyncio_fixture
async def provider_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _make_provider(factory, **kwargs):
    provider = Provider(
        id=str(uuid.uuid4()),
        name=kwargs.get("name", "P"),
        type=kwargs.get("type", "openai"),
        encrypted_key=encrypt(kwargs["api_key"]) if kwargs.get("api_key") else None,
        base_url=kwargs.get("base_url"),
        org_id=kwargs.get("org_id"),
        extra_params=json.dumps(kwargs.get("extra_params") or {}),
        custom_models=json.dumps(kwargs.get("custom_models") or []),
    )
    async with factory() as db:
        db.add(provider)
        await db.commit()
    return provider.id


class TestOfferings:
    async def test_overrides_false_zero_persist_and_survive(self, provider_db):
        pid = await _make_provider(provider_db, type="openai", api_key="k")
        async with provider_db() as db:
            offering = await update_override(
                db, pid, "gpt-6", {"supports_vision": False, "max_context_tokens": 400000}
            )
            await db.commit()
            assert json.loads(offering.overrides_json)["supports_vision"] is False

        async with provider_db() as db:
            again = await update_override(db, pid, "gpt-6", {"temperature": True})
            await db.commit()
            ov = json.loads(again.overrides_json)
            assert ov["supports_vision"] is False and ov["max_context_tokens"] == 400000

    async def test_override_rejects_garbage(self, provider_db):
        pid = await _make_provider(provider_db, api_key="k")
        async with provider_db() as db:
            try:
                await update_override(db, pid, "m", {"max_context_tokens": "lots"})
                assert False
            except ValueError:
                pass

    async def test_revision_appends_on_change(self, provider_db):
        pid = await _make_provider(provider_db, api_key="k")
        async with provider_db() as db:
            o = await update_override(db, pid, "m1", {"supports_vision": True})
            rev1 = o.revision
            o = await update_override(db, pid, "m1", {"supports_thinking": True})
            await db.commit()
            assert o.revision > rev1
            rows = (
                (
                    await db.execute(
                        select(ModelCatalogRevision).where(ModelCatalogRevision.offering_id == o.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) >= 2


class TestFingerprint:
    def test_config_change_produces_new_fingerprint(self):
        a = {
            "type": "openai",
            "api_key": "k1",
            "base_url": None,
            "org_id": None,
            "extra_params": {},
        }
        b = dict(a, base_url="https://proxy.local")
        c = dict(a, api_key="k2")
        assert _fingerprint(a) != _fingerprint(b) != _fingerprint(c)


class TestDiscoveryStates:
    async def test_failed_discovery_marks_unknown_not_unavailable(self, provider_db):
        from agentos.providers import model_catalog as mc

        pid = await _make_provider(provider_db, type="openai", api_key="sk-bad")
        async with provider_db() as db:
            # seed an available offering
            o = ModelCatalogOffering(
                provider_id=pid,
                model_id="gpt-6",
                observations_json="{}",
                overrides_json="{}",
                resolved_json="{}",
                discovery_state="available",
            )
            db.add(o)
            await db.commit()

        async def fail(_provider):
            raise RuntimeError("connection refused")

        orig = mc.discover_provider_models
        mc.discover_provider_models = fail
        try:
            await mc._refresh_provider(pid, provider_db, __import__("asyncio").Lock())
        finally:
            mc.discover_provider_models = orig

        async with provider_db() as db:
            row = (
                await db.execute(
                    select(ModelCatalogOffering).where(ModelCatalogOffering.provider_id == pid)
                )
            ).scalar_one()
            assert row.discovery_state == "unknown"
            assert row.discovery_error

    async def test_complete_empty_discovery_marks_absent_unavailable(self, provider_db):
        from agentos.providers import model_catalog as mc

        pid = await _make_provider(provider_db, type="openai", api_key="k")
        async with provider_db() as db:
            db.add(
                ModelCatalogOffering(
                    provider_id=pid,
                    model_id="gone",
                    observations_json="{}",
                    overrides_json="{}",
                    resolved_json="{}",
                    discovery_state="available",
                )
            )
            await db.commit()

        orig = mc.discover_provider_models
        mc.discover_provider_models = lambda _p: asyncio.sleep(0, [])
        try:
            await mc._refresh_provider(pid, provider_db, __import__("asyncio").Lock())
        finally:
            mc.discover_provider_models = orig

        async with provider_db() as db:
            row = (
                await db.execute(
                    select(ModelCatalogOffering).where(ModelCatalogOffering.provider_id == pid)
                )
            ).scalar_one()
            assert row.discovery_state == "unavailable"


def test_sdk_cost_map_flag_set_on_import():
    """C11 (partial): importing agentos pins the remote cost-map off.
    Full ownership lands when accounting migrates next slice."""
    import os
    import subprocess
    import sys

    code = "import agentos; import os; assert os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] == 'True'"
    env = {**os.environ}
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


class TestSettingsApi:
    @pytest_asyncio_fixture
    async def api(self, tmp_path, db_engine, monkeypatch):
        import bcrypt
        from httpx import ASGITransport, AsyncClient

        from agentos.db import get_db
        from agentos.main import app
        from agentos.models.operator import Operator

        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            db.add(
                Operator(
                    id=str(uuid.uuid4()),
                    username="admin",
                    password_hash=bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),
                )
            )
            await db.commit()

        async def override_get_db():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db

        # Pin the persisted-settings path to tmp — PUT must not touch real data.
        from agentos.config import settings

        monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")

        # Snapshot pointed at a throwaway store — fetcher that must never run on GET.
        bundled = tmp_path / "b.json"
        bundled.write_bytes(_tiny_catalog())
        snap = CatalogSnapshot(store_dir=tmp_path / "store", bundled_path=bundled)
        monkeypatch.setattr(catalog_mod, "_snapshot", snap)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            login = await c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
            yield c, {"Authorization": f"Bearer {login.json()['session_token']}"}
        app.dependency_overrides.clear()

    async def test_status_never_fetches(self, api, monkeypatch):
        client, headers = api

        def boom():
            raise AssertionError("network on status read")

        monkeypatch.setattr(catalog_mod, "_default_fetcher", boom)
        resp = await client.get("/api/settings/model-catalog", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        # Internal daily refresh is on by default — status only READS it.
        assert body["auto_refresh"] is True
        assert body["available"] is True and body["source"] == "bundled"

    async def test_toggle_and_explicit_refresh(self, api):
        client, headers = api
        from agentos.config import settings

        prior = settings.model_catalog_auto_refresh
        try:
            resp = await client.put(
                "/api/settings/model-catalog",
                json={"auto_refresh": True},
                headers=headers,
            )
            assert resp.status_code == 200 and resp.json()["auto_refresh"] is True
            assert settings.model_catalog_auto_refresh is True
        finally:
            # Restore the prior operator value — never hardcode a default
            # back (the test env may be the operator's real setting).
            settings.model_catalog_auto_refresh = prior


# --- lead-review regressions (a–g) -------------------------------------


class TestSnapshotHardening:
    async def test_failed_first_refresh_keeps_bundled_no_keyerror(self, tmp_path):
        bundled = tmp_path / "b.json"
        bundled.write_bytes(_tiny_catalog())
        snap = CatalogSnapshot(store_dir=tmp_path / "store", bundled_path=bundled)

        async def boom():
            raise RuntimeError("offline")

        result = await snap.refresh(fetcher=boom)
        assert result["ok"] is False
        st = snap.status()
        assert st["available"] and st["source"] == "bundled" and st["last_error"]
        assert snap.lookup("openai", "gpt-6") is not None

    async def test_corrupt_active_pointer_falls_back_to_bundled(self, tmp_path):
        bundled = tmp_path / "b.json"
        bundled.write_bytes(_tiny_catalog())
        store = tmp_path / "store"
        snap = CatalogSnapshot(store_dir=store, bundled_path=bundled)
        # Non-hex pointer + path-escape attempt both stay inert.
        store.mkdir(parents=True)
        (store / "active.json").write_text(json.dumps({"sha256": "../bundled.json"}))
        st = snap.status()
        assert st["source"] == "bundled"
        # 64-hex shape but the file's hash doesn't match the pointer.
        (store / "active.json").write_text(json.dumps({"sha256": "a" * 64, "fetched_at": "x"}))
        assert snap.status()["source"] == "bundled"

    async def test_bad_payload_keeps_last_good(self, tmp_path):
        bundled = tmp_path / "b.json"
        bundled.write_bytes(_tiny_catalog())
        snap = CatalogSnapshot(store_dir=tmp_path / "store", bundled_path=bundled)
        ok = await snap.refresh(fetcher=lambda: asyncio.sleep(0, _tiny_catalog()))
        assert ok["ok"]
        for bad in (
            b'{"x": {"models": {"m": {"name": "M", "cost": {"input": NaN, "output": 1}}}}}',
            b'{"x": {"models": {"m": {"name": "M", "reasoning": "yes"}}}}',
            b'{"x": {"models": {"m": {"limit": {"input": true}}}}}',
        ):
            result = await snap.refresh(fetcher=lambda b=bad: asyncio.sleep(0, b))
            assert not result["ok"], bad[:50]
            assert snap.status()["revision"] == ok["revision"]

    def test_lookup_parses_once_not_per_call(self, snapshot):
        import agentos.providers.catalog as c

        calls = 0
        orig = c.decode_catalog

        def counted(b):
            nonlocal calls
            calls += 1
            return orig(b)

        c.decode_catalog = counted
        try:
            for _ in range(5):
                snapshot.lookup("openai", "gpt-6")
                snapshot.models("openai")
        finally:
            c.decode_catalog = orig
        assert calls <= 2  # bundled decoded once, cached thereafter

    def test_lookup_returns_copies_not_cache_refs(self, snapshot):
        entry = snapshot.lookup("openai", "gpt-6")
        entry["limit"]["context"] = -1
        assert snapshot.lookup("openai", "gpt-6")["limit"]["context"] == 400000


class TestFetchGuards:
    async def test_off_origin_redirect_never_requested(self, monkeypatch):
        import httpx

        from agentos.providers import catalog as c

        requested = []

        class FakeResp:
            def __init__(self, status, url):
                self.status_code = status
                self.url = url
                self.headers = {"location": "https://evil.example/steal"}
                self.is_redirect = True

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def raise_for_status(self):
                pass

        class FakeClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, **kw):
                requested.append(url)
                if "evil" in url:
                    raise AssertionError("off-origin request attempted")
                return FakeResp(302, url)

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        try:
            await c._default_fetcher()
            assert False, "should have raised"
        except ValueError as e:
            assert "origin" in str(e)
        assert all("models.dev" in u for u in requested)


class TestRefreshJobs:
    async def test_dedup_and_provider_task_registry(self, provider_db):
        from agentos.providers import model_catalog as mc

        pid = await _make_provider(provider_db, type="openai", api_key="k")

        async def slow(_p):
            await asyncio.sleep(0.2)
            return []

        orig = mc.discover_provider_models
        mc.discover_provider_models = slow
        try:
            await mc.refresh_provider(pid, provider_db)
            await mc.refresh_provider(pid, provider_db)  # dedup while running
            assert len([t for t in mc._provider_tasks.values() if not t.done()]) == 1
            await asyncio.sleep(0.4)
        finally:
            mc.discover_provider_models = orig

    async def test_stale_config_mid_fetch_discards_results(self, provider_db):
        from agentos.providers import model_catalog as mc

        pid = await _make_provider(provider_db, type="openai", api_key="k")

        async def delayed(_p):
            # flip the config mid-flight — the fetch result must be dropped
            async with provider_db() as db:
                row = (await db.execute(select(Provider).where(Provider.id == pid))).scalar_one()
                row.base_url = "https://moved.example/v1"
                await db.commit()
            return [{"id": "stale-model", "name": "stale-model"}]

        orig = mc.discover_provider_models
        mc.discover_provider_models = delayed
        try:
            await mc._refresh_provider(pid, provider_db, __import__("asyncio").Lock())
        finally:
            mc.discover_provider_models = orig
        async with provider_db() as db:
            count = (
                (
                    await db.execute(
                        select(ModelCatalogOffering).where(ModelCatalogOffering.provider_id == pid)
                    )
                )
                .scalars()
                .all()
            )
            assert count == []  # discarded, no orphan writes


class TestReadViews:
    async def test_virtual_catalog_entries_surface_without_writes(
        self, provider_db, monkeypatch, tmp_path
    ):
        from agentos.providers import model_catalog as mc

        bundled = tmp_path / "b.json"
        bundled.write_bytes(_tiny_catalog())
        snap = catalog_mod.CatalogSnapshot(store_dir=tmp_path / "store", bundled_path=bundled)
        monkeypatch.setattr(mc, "get_catalog_snapshot", lambda: snap)

        pid = await _make_provider(provider_db, type="openai", api_key="k")
        # cold provider, no stored rows, no discovery — catalog still answers
        async with provider_db() as db:
            offerings = await mc.list_offerings(db, pid)
        ids = {o.model_id for o in offerings}
        assert "gpt-6" in ids  # bundled catalog virtual entry
        # and it's resolved through the catalog provenance, not a write
        assert all(o.discovery_state == "unknown" for o in offerings)

    async def test_config_change_invalidates_stored_observations(self, provider_db):
        from agentos.providers import model_catalog as mc

        pid = await _make_provider(provider_db, type="openai", api_key="k")
        fingerprint = mc._fingerprint(
            {
                "type": "openai",
                "api_key": "k",
                "base_url": None,
                "org_id": None,
                "extra_params": {},
                "custom_models": [],
            }
        )
        async with provider_db() as db:
            db.add(
                ModelCatalogOffering(
                    provider_id=pid,
                    model_id="m1",
                    observations_json='{"max_context_tokens": 999}',
                    overrides_json="{}",
                    resolved_json="{}",
                    discovery_state="available",
                    config_fingerprint=fingerprint,
                )
            )
            await db.commit()
        # move the proxy — old observations must not apply
        async with provider_db() as db:
            row = (await db.execute(select(Provider).where(Provider.id == pid))).scalar_one()
            row.base_url = "https://other.example/v1"
            await db.commit()
        async with provider_db() as db:
            views = await mc.list_offerings(db, pid)
        view = next(v for v in views if v.model_id == "m1")
        resolved = json.loads(view.resolved_json)
        assert view.discovery_state == "unknown"
        assert resolved["provenance"]["max_context_tokens"]["source"] != "provider"


class TestDiscoveryTruthfulness:
    async def test_anthropic_no_invented_fields(self, monkeypatch):
        import httpx

        from agentos.providers.model_catalog import _discover_anthropic

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "data": [
                        {
                            "id": "claude-x",
                            "display_name": "Claude X",
                            # no capabilities at all — nothing may be invented
                        }
                    ],
                    "has_more": False,
                }

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return Resp()

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: Client())
        result = await _discover_anthropic({"api_key": "k", "base_url": None})
        model = result["models"][0]
        assert model["supports_vision"] is None
        assert model["supports_thinking"] is None
        assert model["thinking_efforts"] is None
        assert model["max_context_tokens"] is None

    async def test_error_text_carries_no_key(self, provider_db):
        from agentos.providers import model_catalog as mc

        pid = await _make_provider(
            provider_db, type="gemini", api_key="SECRETKEY123", base_url="https://g.example"
        )

        async def boom(_p):
            raise RuntimeError("401 GET https://g.example/models?key=SECRETKEY123")

        orig = mc.discover_provider_models
        mc.discover_provider_models = boom
        try:
            await mc._refresh_provider(pid, provider_db, __import__("asyncio").Lock())
            # seed an unavailable→unknown transition
            async with provider_db() as db:
                db.add(
                    ModelCatalogOffering(
                        provider_id=pid,
                        model_id="m",
                        observations_json="{}",
                        overrides_json="{}",
                        resolved_json="{}",
                        discovery_state="available",
                    )
                )
                await db.commit()
            await mc._refresh_provider(pid, provider_db, __import__("asyncio").Lock())
        finally:
            mc.discover_provider_models = orig
        async with provider_db() as db:
            row = (
                await db.execute(
                    select(ModelCatalogOffering).where(ModelCatalogOffering.provider_id == pid)
                )
            ).scalar_one()
            assert "SECRETKEY123" not in (row.discovery_error or "")
            assert row.discovery_state == "unknown"

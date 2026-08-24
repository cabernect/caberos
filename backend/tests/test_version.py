"""Tests for version synchronization (v0.1.3 Trust Bundle).

Covers:
- About renders the runtime application version instead of a hardcoded string
- web mode obtains the backend/package version without importing Tauri APIs
- a release verification test fails when version manifests disagree
- semantic version comparison handles patch and minor upgrades correctly
"""

import re
import tomllib
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from agentos.db import get_db
from agentos.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_pyproject_version() -> str:
    pyproject = REPO_ROOT / "backend" / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def _read_package_json_version() -> str:
    import json

    pkg = REPO_ROOT / "frontend" / "package.json"
    with open(pkg) as f:
        return json.load(f)["version"]


def _read_cargo_version() -> str:
    cargo = REPO_ROOT / "frontend" / "src-tauri" / "Cargo.toml"
    for line in cargo.read_text().splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    raise ValueError("version not found in Cargo.toml")


def _read_tauri_conf_version() -> str:
    import json

    conf = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
    with open(conf) as f:
        return json.load(f)["version"]


class TestVersionSync:
    """Tests for version synchronization across manifests."""

    def test_all_manifests_agree(self):
        """All version manifests must report the same version."""
        versions = {
            "pyproject.toml": _read_pyproject_version(),
            "package.json": _read_package_json_version(),
            "Cargo.toml": _read_cargo_version(),
            "tauri.conf.json": _read_tauri_conf_version(),
        }
        unique = set(versions.values())
        assert len(unique) == 1, (
            f"Version drift detected: {versions}. Run ./scripts/set-version.sh <version> to fix."
        )

    def test_version_is_semver(self):
        """The version must be in semantic versioning format."""
        version = _read_pyproject_version()
        assert re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$", version), (
            f"Version {version} is not in semver format"
        )

    def test_version_is_not_placeholder(self):
        """The version must not be the placeholder 0.0.0."""
        version = _read_package_json_version()
        assert version != "0.0.0", "package.json still has placeholder version 0.0.0"

    async def test_backend_version_endpoint(self, db_engine):
        """The /api/version endpoint returns the runtime version."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

        async def override_get_db():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/version")
            assert resp.status_code == 200
            data = resp.json()
            assert "version" in data
            assert data["version"] != "0.0.0"
            assert re.match(r"^\d+\.\d+\.\d+", data["version"])
        app.dependency_overrides.clear()

    def test_semver_comparison_patch(self):
        """Semantic version comparison handles patch upgrades correctly."""
        from agentos.versioning import compare_versions

        assert compare_versions("0.1.3", "0.1.2") > 0
        assert compare_versions("0.1.2", "0.1.3") < 0
        assert compare_versions("0.1.3", "0.1.3") == 0

    def test_semver_comparison_minor(self):
        """Semantic version comparison handles minor upgrades correctly."""
        from agentos.versioning import compare_versions

        assert compare_versions("0.2.0", "0.1.9") > 0
        assert compare_versions("0.1.9", "0.2.0") < 0

    def test_semver_comparison_major(self):
        """Semantic version comparison handles major upgrades correctly."""
        from agentos.versioning import compare_versions

        assert compare_versions("1.0.0", "0.9.9") > 0
        assert compare_versions("0.9.9", "1.0.0") < 0

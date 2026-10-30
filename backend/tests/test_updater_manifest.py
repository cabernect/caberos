"""Test the updater manifest builder.

The manifest is the one artifact in the release pipeline whose failure mode is
silent: a manifest missing a platform does not error anywhere, it just stops
that platform's users from ever seeing another update. These tests exist to
make that specific mistake impossible to ship.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build-updater-manifest.py"
_spec = importlib.util.spec_from_file_location("build_updater_manifest", _SCRIPT)
assert _spec and _spec.loader
manifest_mod = importlib.util.module_from_spec(_spec)
sys.modules["build_updater_manifest"] = manifest_mod
_spec.loader.exec_module(manifest_mod)

ManifestError = manifest_mod.ManifestError
build_manifest = manifest_mod.build_manifest


@pytest.fixture
def artifact(tmp_path):
    """Create an artifact plus its detached signature."""

    def _make(name: str, signature: str = "sig-content") -> Path:
        path = tmp_path / name
        path.write_bytes(b"archive")
        path.with_name(path.name + ".sig").write_text(signature, encoding="utf-8")
        return path

    return _make


def test_builds_both_platforms(artifact):
    """A two-platform release yields both keys with correct download URLs."""
    manifest = build_manifest(
        version="0.3.0",
        repo="cabernect/caberos",
        tag="v0.3.0",
        artifacts={
            "darwin-aarch64": artifact("CaberOS.app.tar.gz"),
            "windows-x86_64": artifact("CaberOS_0.3.0_x64-setup.nsis.zip"),
        },
    )

    assert set(manifest["platforms"]) == {"darwin-aarch64", "windows-x86_64"}
    assert manifest["version"] == "0.3.0"
    win = manifest["platforms"]["windows-x86_64"]
    assert win["url"].endswith("/v0.3.0/CaberOS_0.3.0_x64-setup.nsis.zip")
    assert win["signature"] == "sig-content"


def test_missing_expected_platform_is_refused(artifact):
    """Dropping a platform must fail loudly, never publish a partial manifest.

    This is the regression that would strand every existing macOS install when
    a Windows-only job overwrites the manifest.
    """
    with pytest.raises(ManifestError, match="missing expected platform"):
        build_manifest(
            version="0.3.0",
            repo="cabernect/caberos",
            tag="v0.3.0",
            artifacts={"windows-x86_64": artifact("setup.nsis.zip")},
            expected_platforms={"darwin-aarch64", "windows-x86_64"},
        )


def test_all_expected_platforms_present_passes(artifact):
    """The same check passes once every expected platform is supplied."""
    manifest = build_manifest(
        version="0.3.0",
        repo="cabernect/caberos",
        tag="v0.3.0",
        artifacts={
            "darwin-aarch64": artifact("CaberOS.app.tar.gz"),
            "windows-x86_64": artifact("setup.nsis.zip"),
        },
        expected_platforms={"darwin-aarch64", "windows-x86_64"},
    )
    assert len(manifest["platforms"]) == 2


def test_missing_signature_is_refused(tmp_path):
    """An archive without its .sig cannot be published."""
    orphan = tmp_path / "CaberOS.app.tar.gz"
    orphan.write_bytes(b"archive")

    with pytest.raises(ManifestError, match="Missing signature"):
        build_manifest(
            version="0.3.0",
            repo="cabernect/caberos",
            tag="v0.3.0",
            artifacts={"darwin-aarch64": orphan},
        )


def test_empty_signature_is_refused(artifact):
    """An empty signature would produce a manifest clients silently reject."""
    with pytest.raises(ManifestError, match="empty"):
        build_manifest(
            version="0.3.0",
            repo="cabernect/caberos",
            tag="v0.3.0",
            artifacts={"darwin-aarch64": artifact("CaberOS.app.tar.gz", signature="   ")},
        )


def test_unknown_platform_key_is_refused(artifact):
    """A typo'd platform key is ignored by clients, so reject it at build time."""
    with pytest.raises(ManifestError, match="Unknown Tauri platform key"):
        build_manifest(
            version="0.3.0",
            repo="cabernect/caberos",
            tag="v0.3.0",
            artifacts={"win32-x64": artifact("setup.nsis.zip")},
        )


def test_empty_manifest_is_refused():
    """Never write a manifest with no platforms at all."""
    with pytest.raises(ManifestError, match="No platform artifacts"):
        build_manifest(version="0.3.0", repo="cabernect/caberos", tag="v0.3.0", artifacts={})

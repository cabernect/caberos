"""Fernet secret store for encrypting API keys and connector tokens."""

import getpass
import logging
import os
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from .config import settings

logger = logging.getLogger(__name__)


def _restrict_to_current_user(key_path: Path) -> None:
    """Make the key file readable only by the user who owns it.

    chmod(0o600) is a no-op for access control on Windows — it only toggles the
    read-only attribute, leaving the key readable by every other local account.
    Since this key decrypts every stored provider API key and MCP credential,
    Windows needs a real ACL: drop inherited permissions, grant the current
    user only.
    """
    if sys.platform != "win32":
        key_path.chmod(0o600)
        return

    user = os.environ.get("USERNAME") or getpass.getuser()
    try:
        result = subprocess.run(
            ["icacls", str(key_path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning(
                "Could not restrict permissions on the secret key at %s. "
                "It may be readable by other users on this machine. icacls said: %s",
                key_path,
                result.stderr.decode("utf-8", errors="replace").strip(),
            )
    except Exception as exc:  # pragma: no cover — depends on host tooling
        logger.warning(
            "Could not restrict permissions on the secret key at %s: %s. "
            "It may be readable by other users on this machine.",
            key_path,
            exc,
        )


def _get_or_create_key() -> bytes:
    """Load the encryption key, or generate one on first run."""
    key_path = settings.secret_key_path
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        # Ensure secure permissions on existing key files
        try:
            _restrict_to_current_user(key_path)
        except (OSError, PermissionError):
            pass  # best-effort — may not have permission on some systems
        return key_path.read_bytes()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    _restrict_to_current_user(key_path)
    return key


_fernet: Fernet | None = None


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_or_create_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns the Fernet token as a string."""
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token string. Returns the plaintext."""
    return get_fernet().decrypt(ciphertext.encode()).decode()

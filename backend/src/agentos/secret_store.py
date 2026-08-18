"""Fernet secret store for encrypting API keys and connector tokens."""

from cryptography.fernet import Fernet

from .config import settings


def _get_or_create_key() -> bytes:
    """Load the encryption key, or generate one on first run."""
    key_path = settings.secret_key_path
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        # Ensure secure permissions on existing key files
        try:
            key_path.chmod(0o600)
        except (OSError, PermissionError):
            pass  # best-effort — may not have permission on some systems
        return key_path.read_bytes()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    key_path.chmod(0o600)
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

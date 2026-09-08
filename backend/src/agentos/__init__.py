"""CaberOS — local-first AI Agent Operating System."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agentos")
except PackageNotFoundError:
    __version__ = "unknown"

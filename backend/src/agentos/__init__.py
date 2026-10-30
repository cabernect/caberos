"""CaberOS — local-first AI Agent Operating System."""

import os
from importlib.metadata import PackageNotFoundError, version

# LiteLLM is execution transport only — pin the remote cost-map off
# before the first import so startup stays offline; the bundled models.dev
# snapshot is the catalog/pricing authority.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
try:
    __version__ = version("agentos")
except PackageNotFoundError:
    __version__ = "unknown"

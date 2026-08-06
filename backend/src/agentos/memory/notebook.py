"""MEMORY.md — agent-curated notebook (D34).

A markdown file at ~/agentos/agents/{agent_id}/MEMORY.md.
The harness reads it at context assembly (always loaded).
The agent updates it via the memory_update capability (audited syscall).
Not versioned with AgentVersion — living document.
"""

from ..config import settings


def _memory_path(agent_id: str):
    """Get the path to the agent's MEMORY.md file."""
    from pathlib import Path

    return Path(settings.agent_home_root) / agent_id / "MEMORY.md"


def read_memory(agent_id: str) -> str:
    """Read MEMORY.md content. Returns empty string if file doesn't exist."""
    path = _memory_path(agent_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def write_memory(agent_id: str, content: str) -> int:
    """Write MEMORY.md content. Creates the dir if needed. Returns bytes written."""
    path = _memory_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return len(content)

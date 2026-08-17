"""Automatic promotion of durable conversation facts into MEMORY.md."""

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


def merge_auto_extracted_memory(existing: str, new_lines: list[str]) -> str:
    """Keep all auto-extracted facts under one deduplicated section."""
    manual_lines: list[str] = []
    auto_lines: list[str] = []
    in_auto_section = False

    for raw_line in existing.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"##\s+Auto-extracted", line, flags=re.IGNORECASE):
            in_auto_section = True
            continue
        if in_auto_section and re.match(r"^##\s+", line):
            in_auto_section = False
        if in_auto_section:
            if line.startswith("- "):
                auto_lines.append(line)
        else:
            manual_lines.append(raw_line.rstrip())

    auto_lines.extend(line.strip() for line in new_lines if line.strip().startswith("- "))
    unique_auto_lines: list[str] = []
    seen: set[str] = set()
    for line in auto_lines:
        key = line.casefold()
        if key not in seen:
            seen.add(key)
            unique_auto_lines.append(line)

    manual = "\n".join(manual_lines).rstrip()
    if not unique_auto_lines:
        return f"{manual}\n" if manual else ""

    auto_section = "## Auto-extracted\n\n" + "\n".join(unique_auto_lines)
    return f"{manual}\n\n{auto_section}\n" if manual else f"{auto_section}\n"


async def auto_extract_memory(
    db: AsyncSession,
    agent_config: Any,
    agent_id: str,
    messages: list[Any],
    run_id: str | None = None,
) -> None:
    """Extract durable facts after a run and promote them into MEMORY.md.

    The pipeline owns when this runs; this module owns extraction, merging,
    persistence, and cleanup of run-scoped working memory.
    """
    try:
        from ..providers import ProviderRegistry
        from . import notebook, recall

        convo = []
        for msg in messages:
            if msg.role in ("user", "assistant") and msg.content:
                role = "User" if msg.role == "user" else "Assistant"
                convo.append(f"{role}: {msg.content[:300]}")
            if len(convo) >= 8:
                break

        if not convo:
            return

        working_entries = []
        if run_id:
            working_entries = await recall.get_run_entries(db, run_id)
        await db.commit()

        existing = notebook.read_memory(agent_id)
        prompt = (
            "You are a memory extraction system. Review this conversation and extract "
            "durable facts worth remembering for future sessions.\n\n"
            "Extract ONLY:\n"
            "- User preferences and working habits\n"
            "- Project context (names, file formats, recurring tasks)\n"
            "- Important decisions or constraints\n"
            "- Patterns that will recur in future conversations\n\n"
            "Do NOT extract:\n"
            "- One-off task results (e.g. 'extracted 3 rows from PDF')\n"
            "- Transient state or temporary file contents\n"
            "- Things already in the existing memory\n\n"
        )
        if existing:
            prompt += f"## Existing MEMORY.md\n\n{existing}\n\n"
            prompt += "Only extract NEW information not already captured above.\n\n"
        if working_entries:
            prompt += "## Working memory notes (agent flagged these as important)\n\n"
            for entry in working_entries:
                prompt += f"- [{entry['key']}] {entry['value']}\n"
            prompt += "\n"
        prompt += "## Recent conversation\n\n" + "\n".join(convo) + "\n\n"
        prompt += (
            "Output a markdown list of new facts to remember, one per line, "
            "prefixed with '- '. If there is nothing worth remembering, "
            "output exactly: NOTHING_TO_REMEMBER"
        )

        adapter = await ProviderRegistry(db).for_model(agent_config.model.provider_id)
        response = await adapter.complete(
            agent_model=agent_config.model,
            messages=[{"role": "user", "content": prompt}],
            tools=None,
        )
        await db.commit()

        result = response.content.strip()
        new_lines = [] if not result or result == "NOTHING_TO_REMEMBER" else result.splitlines()
        merged = merge_auto_extracted_memory(existing, new_lines)
        if merged != existing:
            notebook.write_memory(agent_id, merged)

        if run_id:
            await recall.clear_run_entries(db, run_id)
            await db.commit()
    except Exception:
        pass

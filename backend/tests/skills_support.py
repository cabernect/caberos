"""Shared helpers for the W6 skills test files."""

import io
import zipfile
from pathlib import Path


def write_skill(root: Path, name: str, description: str = "a skill", body: str = "Body.") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return d


def zip_bytes(files: dict[str, bytes | str], symlink: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            info = zipfile.ZipInfo(name)
            if symlink:
                info.external_attr = 0o120777 << 16  # unix symlink
            zf.writestr(info, content)
    return buf.getvalue()

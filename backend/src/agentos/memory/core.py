"""Bounded agent core — managed identity + curated MEMORY.md, revision-pinned.

File format (MEMORY.md is the authoritative editable document):

    <!-- caberos:core-identity v1 sha256:{hex} -->
    {managed identity markdown — soul/persona/task, immutable}
    <!-- /caberos:core-identity -->
    {curated content — operator/agent editable}

- The managed prefix is generated deterministically from the authoritative
  DB identity and carries a SHA256 of the identity text — no config UUID in
  the file, so model-only config edits don't invalidate it. The source
  version is revision metadata only.
- Everything below the managed block is curated content. A file with no
  marker is a legacy plain notebook — its exact bytes are preserved before
  wrapping.
- Core is agent-global and owner/personal in audience; its archive inherits
  the same audience. No per-contact files, no cross-agent sharing.
- Writers: dashboard PUT, memory_update tool, post-run learning, identity
  sync, restore — all go through update_core so every write is validated,
  hash-checked, atomically published, and snapshotted as a CoreRevision.
- All publication is serialized per agent; the file hash is re-verified
  inside the lock immediately before the atomic replace.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from ..config import settings
from ..models.core import CoreRevision
from ..models.session import Session
from ..services.context_capture import capture_scope

IDENTITY_BEGIN = "<!-- caberos:core-identity v1 sha256:"
IDENTITY_END = "<!-- /caberos:core-identity -->"

# Per-agent serialization of publish operations (dashboard/tool/learning).
_agent_locks: dict[str, asyncio.Lock] = {}


def _lock_for(agent_id: str) -> asyncio.Lock:
    lock = _agent_locks.get(agent_id)
    if lock is None:
        lock = _agent_locks[agent_id] = asyncio.Lock()
    return lock


class CoreConflict(Exception):
    """Recoverable conflict — carries current state for safe explicit retry."""

    def __init__(
        self,
        message: str,
        current_hash: str | None = None,
        current_curated: str | None = None,
        kind: str = "conflict",
    ):
        super().__init__(message)
        self.current_hash = current_hash
        self.current_curated = current_curated
        self.kind = kind


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _identity_text(config: Any) -> str:
    """Deterministic render of the managed identity from authoritative config."""
    parts = []
    if config.soul:
        parts.append(f"## Soul\n\n{config.soul}")
    if config.persona:
        parts.append(f"## Persona\n\n{config.persona}")
    if config.task:
        parts.append(f"## Task\n\n{config.task}")
    return "\n\n".join(parts)


def _core_dir(agent_id: str) -> Path:
    """Agent home dir resolved under the configured root — symlink escapes
    and traversal are rejected before any read/write."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", agent_id):
        raise ValueError("Invalid agent id")
    root = Path(settings.agent_home_root).resolve()
    raw = root / agent_id
    candidate = raw.resolve()
    if candidate != raw or root not in candidate.parents:
        raise CoreConflict("Agent home resolves outside the configured root")
    if raw.is_symlink():
        raise CoreConflict("Agent home must not be a symlink")
    return raw


def _core_path(agent_id: str) -> Path:
    path = _core_dir(agent_id) / "MEMORY.md"
    if path.is_symlink():
        raise CoreConflict("MEMORY.md must not be a symlink")
    return path


def _read_disk(path: Path) -> str:
    """Exact bytes — byte-level decode so CRLF/newlines roundtrip."""
    if not path.exists():
        return ""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CoreConflict("MEMORY.md is not valid UTF-8") from exc


def _write_atomic(path: Path, content: str) -> None:
    """fsync'd temp file + os.replace, mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".MEMORY", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def split_core(content: str) -> tuple[str | None, str | None, str]:
    """Split a file into (recorded identity sha, identity text, curated).

    Legacy plain notebook → (None, None, whole content). The managed block
    is located by the generated prefix; when identity text itself contains
    the end marker, every candidate marker is tried and the split whose
    identity hashes to the recorded sha wins. Malformed → CoreConflict.
    """
    if not content.startswith(IDENTITY_BEGIN):
        if IDENTITY_BEGIN in content:
            raise CoreConflict("Managed identity marker is not at the file start")
        return None, None, content
    open_end = content.find("-->", len(IDENTITY_BEGIN))
    if open_end < 0:
        raise CoreConflict("Managed identity marker is unterminated")
    recorded_sha = content[len(IDENTITY_BEGIN) : open_end].strip()
    start = open_end + 3
    search_from = start
    while True:
        end_marker = content.find(IDENTITY_END, search_from)
        if end_marker < 0:
            raise CoreConflict("Managed identity end marker is missing or tampered")
        # The generated format wraps identity with exactly one LF each side.
        # Strip exactly those — user text (trailing newlines, CRLF) survives.
        raw_identity = content[start:end_marker]
        if raw_identity.startswith("\n"):
            raw_identity = raw_identity[1:]
        if raw_identity.endswith("\n"):
            raw_identity = raw_identity[:-1]
        identity = raw_identity
        if _sha256(identity) == recorded_sha:
            # build_core separates with exactly one blank line — remove only
            # that separator so curated newlines roundtrip byte-exact.
            rest = content[end_marker + len(IDENTITY_END) :]
            if rest.startswith("\n\n"):
                curated = rest[2:]
            elif rest.startswith("\n"):
                curated = rest[1:]
            else:
                curated = rest
            return recorded_sha, identity, curated
        search_from = end_marker + 1


def build_core(identity_text: str, curated: str) -> str:
    return (
        f"{IDENTITY_BEGIN}{_sha256(identity_text)} -->\n"
        f"{identity_text}\n"
        f"{IDENTITY_END}\n\n"
        f"{curated}"
    )


def _validate_curated(curated: str) -> None:
    if IDENTITY_BEGIN in curated or IDENTITY_END in curated:
        raise CoreConflict("Curated memory must not contain managed identity markers")


def core_token_count(content: str) -> int:
    """Core ceiling validation always uses the gpt-4o reference tokenizer —
    independent of the configured provider/model."""
    from ..harness.compaction import count_text_tokens

    return count_text_tokens(content, "gpt-4o")


@dataclass(frozen=True)
class CoreSnapshot:
    """Frozen view of a pinned core revision — safe to reuse across the run."""

    revision_id: str | None
    content: str
    curated_content: str
    content_hash: str
    identity_source_version_id: str | None
    token_count: int


def _snapshot(revision: CoreRevision | None, content: str, curated: str) -> CoreSnapshot:
    return CoreSnapshot(
        revision_id=revision.id if revision else None,
        content=content,
        curated_content=curated,
        content_hash=_sha256(content),
        identity_source_version_id=(revision.identity_source_version_id if revision else None),
        token_count=core_token_count(content),
    )


async def _active_version_id(db: Any, config: Any) -> str | None:
    """The agent's ACTIVE AgentVersion id whose rendered identity matches the
    caller's config fields — a mid-await config save can't stamp old identity
    with the new version id."""
    from ..models.agent import Agent, AgentVersion

    version = await db.scalar(
        select(AgentVersion)
        .join(Agent, Agent.active_version_id == AgentVersion.id)
        .where(Agent.id == config.id, AgentVersion.agent_id == config.id)
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise CoreConflict("Agent active version integrity failure")
    cfg = version.config
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except json.JSONDecodeError:
            cfg = None
    if not isinstance(cfg, dict):
        raise CoreConflict("Agent active configuration is invalid")
    for field in ("soul", "persona", "task"):
        if cfg.get(field, "") != getattr(config, field, ""):
            raise CoreConflict("Agent identity changed; retry with the active configuration")
    return version.id


async def _identity_version(db: Any, agent_id: str, identity_hash: str) -> str | None:
    """Only versioned configuration, not a file's self-reported hash, proves identity."""
    from ..models.agent import AgentVersion

    versions = await db.scalars(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
    )
    for version in versions:
        try:
            data = json.loads(version.config)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        fields = {name: data.get(name, "") for name in ("soul", "persona", "task")}
        if not all(isinstance(value, str) for value in fields.values()):
            continue
        if _sha256(_identity_text(SimpleNamespace(**fields))) == identity_hash:
            return version.id
    return None


async def _record_original_snapshot(
    db: Any, config: Any, disk: str, version_id: str | None
) -> CoreRevision | None:
    """Before any wrap/replace, the exact original bytes become a published
    revision — the archive can always reconstruct what operators had."""
    if not disk:
        return None
    row = await db.scalar(
        select(CoreRevision).where(
            CoreRevision.agent_id == config.id,
            CoreRevision.content_hash == _sha256(disk),
        )
    )
    if row is not None and _sha256(row.content) == row.content_hash:
        row.published = True
        return row
    try:
        recorded_sha, _identity, curated = split_core(disk)
    except CoreConflict:
        raise CoreConflict("Existing MEMORY.md is malformed")
    original_version = None
    if recorded_sha is not None:
        original_version = await _identity_version(db, config.id, recorded_sha)
        if original_version is None:
            raise CoreConflict("Existing managed identity is not from this agent's configuration")
    row = CoreRevision(
        id=uuid.uuid4().hex,
        agent_id=config.id,
        content=disk,
        curated_content=curated if recorded_sha is not None else disk,
        content_hash=_sha256(disk),
        identity_source_version_id=original_version,
        source_refs="[]",
        published=True,
    )
    db.add(row)
    await db.flush()
    return row


async def _publish(
    db: Any,
    config: Any,
    curated: str,
    *,
    source_refs: list[str] | None,
    version_id: str | None,
    expected_whole_hash: str | None = None,
) -> CoreSnapshot:
    """Atomically publish a candidate whole-file, then record the revision.

    The expected disk hash is re-checked inside the lock immediately before
    the atomic replace — a concurrent same-base write loses instead of
    stomping. The original bytes and the unpublished candidate are
    committed BEFORE the file swap so an interrupt leaves both durable.
    """
    agent_id = config.id
    _validate_curated(curated)
    identity = _identity_text(config)
    whole = build_core(identity, curated)
    ceiling = config.limits.core_max_tokens
    tokens = core_token_count(whole)
    if tokens > ceiling:
        raise CoreConflict(f"Core exceeds ceiling: {tokens} tokens > {ceiling}", kind="limit")
    path = _core_path(agent_id)

    async with _lock_for(agent_id):
        if await _active_version_id(db, config) != version_id:
            raise CoreConflict("Agent configuration changed before core publication")
        path = _core_path(agent_id)
        disk = _read_disk(path)
        if disk:
            await _record_original_snapshot(db, config, disk, version_id)
        if expected_whole_hash is not None and _sha256(disk) != expected_whole_hash:
            raise CoreConflict(
                "Core changed since your edit base",
                current_hash=_sha256(disk) if disk else None,
                current_curated=(split_core(disk)[2] if disk else ""),
            )

        candidate = CoreRevision(
            id=uuid.uuid4().hex,
            agent_id=agent_id,
            content=whole,
            curated_content=curated,
            content_hash=_sha256(whole),
            identity_source_version_id=version_id,
            source_refs=json.dumps(source_refs or []),
            published=False,
        )
        db.add(candidate)
        # Candidate + original evidence must be durable before the swap —
        # an interrupt leaves the on-disk bytes matching a recorded revision.
        await db.commit()

        # Re-verify right before replace — an external editor that doesn't
        # take our lock could have landed between commit and swap.
        if expected_whole_hash is not None:
            path = _core_path(agent_id)
            disk2 = _read_disk(path)
            if _sha256(disk2) != expected_whole_hash:
                raise CoreConflict(
                    "Core changed since your edit base",
                    current_hash=_sha256(disk2) if disk2 else None,
                    current_curated=(split_core(disk2)[2] if disk2 else ""),
                )

        _write_atomic(path, whole)

        landed = _read_disk(path)
        if _sha256(landed) != candidate.content_hash:
            raise CoreConflict("Core file was replaced externally during publish")
        candidate.published = True
        await db.commit()
    return _snapshot(candidate, whole, curated)


async def _known_identity_hash(db: Any, agent_id: str, recorded_sha: str) -> bool:
    return await _identity_version(db, agent_id, recorded_sha) is not None


async def load_or_pin_core(db: Any, config: Any, session: Session) -> CoreSnapshot:
    """Load the session's pinned revision, or pin a fresh valid one.

    - Pinned session → the exact stored revision, validated (agent-scoped,
      published, content hash intact). Missing/foreign/corrupt pin →
      conflict — never silently mint a different core.
    - Unpinned session → read MEMORY.md; legacy bytes are preserved
      verbatim inside the new managed wrap; managed files whose identity
      matches the current config or a known versioned configuration keep their
      curated bytes while the prefix regenerates from authoritative config.
      Oversized/invalid files fail clearly — no silent truncation or paid
      cleanup at startup.
    """
    if session.core_revision_id:
        row = await db.get(CoreRevision, session.core_revision_id)
        if (
            row is None
            or row.agent_id != config.id
            or not row.published
            or _sha256(row.content) != row.content_hash
        ):
            raise CoreConflict("Session's pinned core revision is invalid or missing")
        return _snapshot(row, row.content, row.curated_content)

    path = _core_path(config.id)
    disk = _read_disk(path)
    current_identity = _identity_text(config)
    version_id = await _active_version_id(db, config)

    if not disk:
        curated = ""
    elif disk.startswith(IDENTITY_BEGIN):
        recorded_sha, identity_text, curated = split_core(disk)
        if _sha256(identity_text or "") != recorded_sha:
            raise CoreConflict("Managed identity marker was tampered with")
        if recorded_sha != _sha256(current_identity):
            # A stale-but-genuine managed prefix is an upgrade, not tampering
            # — only when its sha matches a revision we actually published.
            if not await _known_identity_hash(db, config.id, recorded_sha):
                raise CoreConflict(
                    "Managed identity does not match current config or a "
                    "known revision; restore an explicit revision instead"
                )
    else:
        # Legacy plain notebook — the whole file is preserved curated bytes.
        curated = disk

    if core_token_count(current_identity) > config.limits.core_max_tokens:
        # Identity alone exceeds the ceiling — config conflict, zero calls.
        raise CoreConflict("Agent identity exceeds the core token ceiling", kind="limit")

    whole = build_core(current_identity, curated)
    if core_token_count(whole) > config.limits.core_max_tokens:
        # Oversized file: preserve the original bytes hash-addressed (no
        # clobber of an earlier backup); the pin needs explicit maintenance.
        if disk:
            backup = path.parent / f"MEMORY.md.pre-core-backup.{_sha256(disk)[:16]}"
            try:
                with backup.open("xb") as stream:
                    backup.chmod(0o600)
                    stream.write(disk.encode("utf-8"))
            except FileExistsError:
                if backup.is_symlink() or backup.read_bytes() != disk.encode("utf-8"):
                    raise CoreConflict("Existing core backup does not match the original")
        raise CoreConflict(
            "MEMORY.md exceeds the core ceiling and needs manual curation; "
            "original preserved alongside it"
        )

    # Already-published bytes → reuse that revision (a new session pins the
    # same revision, not a fresh duplicate snapshot).
    existing = await db.scalar(
        select(CoreRevision)
        .where(
            CoreRevision.agent_id == config.id,
            CoreRevision.content_hash == _sha256(whole),
        )
        .order_by(CoreRevision.published.desc(), CoreRevision.created_at.desc())
        .limit(1)
    )
    if (
        existing is not None
        and _sha256(existing.content) == existing.content_hash
        and (existing.published or _sha256(disk) == existing.content_hash)
    ):
        if not existing.published:
            existing.published = True
            await db.commit()
        session.core_revision_id = existing.id
        await db.flush()
        return _snapshot(existing, existing.content, existing.curated_content)

    snapshot = await _publish(
        db,
        config,
        curated,
        source_refs=None,
        version_id=version_id,
        expected_whole_hash=_sha256(disk),
    )
    session.core_revision_id = snapshot.revision_id
    await db.flush()
    return snapshot


def _reduce_input_to_curated(config: Any, disk: str, incoming: str) -> str:
    """A full-file update whose managed prefix is the valid current one
    contributes only its curated body — never double-wraps the identity."""
    if not incoming.startswith(IDENTITY_BEGIN):
        return incoming
    sha, identity_text, curated = split_core(incoming)
    if sha is not None and _sha256(identity_text or "") == sha == _sha256(_identity_text(config)):
        return curated
    raise CoreConflict("Incoming content carries an unmanaged identity prefix")


async def update_core(
    db: Any,
    config: Any,
    curated_content: str,
    *,
    expected_hash: str | None = None,
    source_refs: list[str] | None = None,
    cleanup: bool = True,
) -> CoreSnapshot:
    """Validate + publish a new curated portion through every writer path.

    `expected_hash` is the whole-file hash the caller based its edit on —
    a mismatch raises CoreConflict carrying the current hash/curated so an
    explicit retry can proceed safely. `cleanup=True` (default) permits a
    single configured-model cleanup attempt when the PROPOSED candidate
    overflows; the rejected proposal is kept as evidence regardless.
    """
    path = _core_path(config.id)
    disk = _read_disk(path)
    current_identity = _identity_text(config)
    if disk:
        recorded_sha, identity_text, _cur = (
            split_core(disk) if disk.startswith(IDENTITY_BEGIN) else (None, None, disk)
        )
        if recorded_sha is not None:
            if _sha256(identity_text or "") != recorded_sha:
                raise CoreConflict("Managed identity marker was tampered with")
            if recorded_sha != _sha256(current_identity) and not await _known_identity_hash(
                db, config.id, recorded_sha
            ):
                raise CoreConflict(
                    "Managed identity differs from the current configuration; "
                    "restore an explicit revision instead"
                )
    incoming = _reduce_input_to_curated(config, disk, curated_content)
    _validate_curated(incoming)

    # Effective CAS base — explicit whole-file hash or the bytes just
    # observed. An explicit stale base rejects BEFORE evidence writes or
    # any cleanup/provider call.
    observed_hash = _sha256(disk)
    if expected_hash is not None and expected_hash != observed_hash:
        raise CoreConflict(
            "Core changed since your edit base",
            current_hash=observed_hash,
            current_curated=(
                split_core(disk)[2] if disk and disk.startswith(IDENTITY_BEGIN) else disk
            ),
        )
    base_hash = expected_hash if expected_hash is not None else observed_hash

    version_id = await _active_version_id(db, config)
    whole = build_core(current_identity, incoming)
    if core_token_count(whole) > config.limits.core_max_tokens:
        # Preserve the rejected candidate as evidence before any cleanup.
        db.add(
            CoreRevision(
                id=uuid.uuid4().hex,
                agent_id=config.id,
                content=whole,
                curated_content=incoming,
                content_hash=_sha256(whole),
                identity_source_version_id=version_id,
                source_refs=json.dumps(source_refs or []),
                published=False,
            )
        )
        await db.commit()
        if not cleanup:
            raise CoreConflict(
                "Core update exceeds the ceiling — run cleanup or narrow the edit",
                kind="limit",
            )
        try:
            return await cleanup_core(
                db, config, proposed_curated=incoming, expected_hash=base_hash
            )
        except CoreConflict as exc:
            if exc.kind == "conflict":
                raise  # CAS/conflict detail must reach the caller as-is
            raise CoreConflict(
                f"Core update exceeds the ceiling; cleanup failed: {exc}",
                kind="limit",
            ) from exc

    return await _publish(
        db,
        config,
        incoming,
        source_refs=source_refs,
        version_id=version_id,
        expected_whole_hash=base_hash,
    )


async def cleanup_core(
    db: Any,
    config: Any,
    proposed_curated: str | None = None,
    expected_hash: str | None = None,
) -> CoreSnapshot:
    """Exactly one configured-model cleanup attempt (never retried).

    On ANY failure — provider, parse, validation, or publication — the old
    published bytes remain and the candidate is already durable evidence.
    The envelope-only core must fit the ceiling BEFORE the model call —
    cleanup can only ever shrink curated text.
    """
    from ..harness.compaction import count_tokens
    from ..harness.memory_prompts import CORE_CURATION_PROMPT
    from ..providers import ProviderRegistry

    path = _core_path(config.id)
    disk = _read_disk(path)
    current_identity = _identity_text(config)
    # Identity alone must leave room — if it doesn't, zero provider calls.
    if core_token_count(build_core(current_identity, "")) > config.limits.core_max_tokens:
        raise CoreConflict("Managed identity alone exceeds the core ceiling")
    current_curated = disk if not disk.startswith(IDENTITY_BEGIN) else split_core(disk)[2]
    proposal = proposed_curated if proposed_curated is not None else current_curated

    # CAS base captured BEFORE the model call — a post-await publish then
    # can't overwrite an external edit landed during the call.
    observed_hash = _sha256(disk)
    if expected_hash is not None and expected_hash != observed_hash:
        raise CoreConflict(
            "Core changed since your edit base",
            current_hash=observed_hash,
            current_curated=current_curated,
        )
    base_hash = expected_hash if expected_hash is not None else observed_hash

    from ..models.agent import Agent

    agent = await db.get(Agent, config.id)
    if agent is None:
        raise CoreConflict(f"Agent {config.id} not found")
    version_id = await _active_version_id(db, config)
    base_revision = await _record_original_snapshot(db, config, disk, version_id)
    proposed_whole = build_core(current_identity, proposal)
    proposal_revision = await db.scalar(
        select(CoreRevision).where(
            CoreRevision.agent_id == config.id,
            CoreRevision.content_hash == _sha256(proposed_whole),
        )
    )
    if proposal_revision is None or proposal_revision.content != proposed_whole:
        proposal_revision = CoreRevision(
            id=uuid.uuid4().hex,
            agent_id=config.id,
            content=proposed_whole,
            curated_content=proposal,
            content_hash=_sha256(proposed_whole),
            identity_source_version_id=version_id,
            source_refs=json.dumps([base_revision.id] if base_revision else []),
            published=False,
        )
        db.add(proposal_revision)
    await db.commit()
    try:
        adapter = await ProviderRegistry(db).for_model(config.model.provider_id)
    except Exception as exc:
        raise CoreConflict("Core cleanup provider unavailable", kind="cleanup") from exc
    capped_model = config.model.model_copy(
        update={"max_tokens": min(config.model.max_tokens or 4096, 4096)}
    )
    # Supplied source ids are real published revision ids — demoted entries
    # may only cite these, and they stay retrievable via the archive.
    supplied_ids = list(
        dict.fromkeys(
            revision.id for revision in (base_revision, proposal_revision) if revision is not None
        )
    )
    payload = json.dumps(
        {
            "existing_curated": current_curated,
            "proposed_curated": proposal,
            "max_tokens": config.limits.core_max_tokens,
            "identity_tokens_reserved": core_token_count(build_core(current_identity, "")),
            "source_ids": supplied_ids,
        }
    )
    request_msgs = [{"role": "user", "content": f"{CORE_CURATION_PROMPT}\n\n{payload}"}]
    # Input must fit the resolved budget for the capped model — no clipping.
    info = await adapter.get_model_info(capped_model)
    from ..providers.catalog_policy import resolve_input_budget

    budget = resolve_input_budget(
        info.get("resolved_model") or {},
        model_override=config.model.max_context_tokens,
        run_override=config.limits.max_context_tokens,
        output_tokens=capped_model.max_tokens,
    )["tokens"]
    if count_tokens(request_msgs, info["model_str"]) > budget:
        raise CoreConflict("Core cleanup input exceeds the resolved budget", kind="cleanup")

    import time as _time

    from ..services.model_ledger import record_system_call

    started = _time.perf_counter()
    try:
        with capture_scope(
            agent_id=config.id,
            purpose="reasoning",
            operation="core_cleanup",
            source_core_revision_ids=supplied_ids,
            identity_source_version_id=version_id,
        ):
            response = await adapter.complete(
                agent_model=capped_model,
                messages=request_msgs,
                tools=None,
            )
        await record_system_call(
            kind="cleanup",
            provider_id=config.model.provider_id,
            model_name=config.model.name,
            model_str=info["model_str"],
            agent_id=config.id,
            response=response,
            latency_ms=int((_time.perf_counter() - started) * 1000),
            detail={"operation": "core_cleanup"},
        )
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        await record_system_call(
            kind="cleanup",
            provider_id=config.model.provider_id,
            model_name=config.model.name,
            model_str=info["model_str"],
            agent_id=config.id,
            error=exc,
            latency_ms=int((_time.perf_counter() - started) * 1000),
            detail={"operation": "core_cleanup"},
        )
        raise CoreConflict("Core cleanup could not complete", kind="cleanup") from exc

    try:
        data = json.loads((getattr(response, "content", "") or "").strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise CoreConflict("Core cleanup returned invalid JSON", kind="cleanup") from exc
    if not isinstance(data, dict) or not isinstance(data.get("core_markdown"), str):
        raise CoreConflict("Core cleanup returned no curated markdown", kind="cleanup")
    demoted = data.get("demoted", [])
    if not isinstance(demoted, list):
        raise CoreConflict("Core cleanup returned invalid demoted entries", kind="cleanup")
    conflicts = data.get("conflicts", [])
    if not isinstance(conflicts, list) or any(not isinstance(c, str) for c in conflicts):
        raise CoreConflict("Core cleanup returned invalid conflicts", kind="cleanup")
    if conflicts:
        raise CoreConflict(f"Core cleanup reported conflicts: {len(conflicts)}", kind="cleanup")
    for d in demoted:
        if (
            not isinstance(d, dict)
            or not isinstance(d.get("text"), str)
            or not isinstance(d.get("source_ids"), list)
            or any(i not in supplied_ids for i in d["source_ids"])
        ):
            raise CoreConflict("Core cleanup returned invalid demoted entries", kind="cleanup")
    new_curated = data["core_markdown"]
    # Credential guard on the whole proposed curated output.
    from ..harness.memory_prompts import MEMORY_CREDENTIAL_ASSIGNMENT_PATTERN
    from ..redaction import redact_text

    candidate_texts = [new_curated, *(entry["text"] for entry in demoted)]
    if any(
        re.search(MEMORY_CREDENTIAL_ASSIGNMENT_PATTERN, text)
        or redact_text(text, max(1, len(text)))[1]
        for text in candidate_texts
    ):
        raise CoreConflict("Core cleanup output contains credential material", kind="cleanup")

    whole = build_core(current_identity, new_curated)
    if core_token_count(whole) > config.limits.core_max_tokens:
        raise CoreConflict("Core cleanup could not fit the ceiling", kind="cleanup")

    # Demoted paragraphs stay searchable — the candidate revision's curated
    # content carries them until the new revision is archived.
    version_id = await _active_version_id(db, config)
    return await _publish(
        db,
        config,
        new_curated,
        source_refs=supplied_ids,
        version_id=version_id,
        expected_whole_hash=base_hash,
    )


async def restore_core(
    db: Any,
    config: Any,
    revision_id: str,
    expected_hash: str | None = None,
) -> CoreSnapshot:
    """Restore a known revision's curated portion under the CURRENT managed
    identity — the revision's own recorded hash must validate first."""
    revision = await db.get(CoreRevision, revision_id)
    if revision is None or revision.agent_id != config.id:
        raise CoreConflict("Unknown core revision")
    recorded_sha, identity_text, _cur = split_core(revision.content)
    if recorded_sha is not None and _sha256(identity_text or "") != recorded_sha:
        raise CoreConflict("Stored revision identity is invalid")
    if _sha256(revision.content) != revision.content_hash:
        raise CoreConflict("Stored revision content hash mismatch")
    if not revision.published:
        raise CoreConflict("Only published revisions can be restored")
    observed = _read_disk(_core_path(config.id))
    observed_hash = _sha256(observed)
    if expected_hash is not None and expected_hash != observed_hash:
        raise CoreConflict("Core changed since your restore base", current_hash=observed_hash)
    version_id = await _active_version_id(db, config)
    return await _publish(
        db,
        config,
        revision.curated_content,
        source_refs=None,
        version_id=version_id,
        expected_whole_hash=expected_hash if expected_hash else observed_hash,
    )

"""Artifact capabilities — structured Office deliverables (W2).

The model works in structured specs/ops; the artifact module guarantees
format validity, workspace containment, revisioning, and provenance.
"""

from typing import Any

from ...artifacts import service
from ...artifacts.service import ArtifactError


def _provenance(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "created_by": kwargs.get("agent_id"),
        "source_run_id": kwargs.get("run_id"),
        "source_message_id": kwargs.get("call_id"),
    }


async def artifact_create(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict:
    """artifact_create(path, format, spec, change_summary?) → tracked artifact."""
    try:
        artifact, rev = await service.create_structured(
            kwargs["db"],
            workspace_id=kwargs["agent_id"],
            workspace_path=workspace_path,
            rel_path=args["path"],
            format=args.get("format") or service._format_of(args["path"]),
            spec=args["spec"],
            change_summary=args.get("change_summary"),
            **_provenance(kwargs),
        )
    except (ArtifactError, KeyError, ValueError) as e:
        return {"error": str(e)}
    return {
        "artifact_id": artifact.id,
        "revision_id": rev.id,
        "revision_number": rev.revision_number,
        "format": artifact.format,
        "path": artifact.current_path,
    }


async def artifact_inspect(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict:
    """artifact_inspect(artifact_id) → validity + structure + tracking state."""
    try:
        return await service.inspect(
            kwargs["db"], args["artifact_id"], workspace_path=workspace_path
        )
    except ArtifactError as e:
        return {"error": str(e)}


async def artifact_revise(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict:
    """artifact_revise(artifact_id, base_revision_id, ops) → new revision."""
    try:
        rev = await service.revise_structured(
            kwargs["db"],
            args["artifact_id"],
            workspace_path=workspace_path,
            base_revision_id=args["base_revision_id"],
            ops=args["ops"],
            change_summary=args.get("change_summary"),
            **_provenance(kwargs),
        )
    except (ArtifactError, KeyError, ValueError) as e:
        return {"error": str(e), "conflict": "changed since base revision" in str(e)}
    return {"revision_id": rev.id, "revision_number": rev.revision_number}


async def artifact_adopt(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict:
    """artifact_adopt(path) → start tracking an existing workspace file."""
    try:
        artifact, rev = await service.adopt(
            kwargs["db"],
            workspace_id=kwargs["agent_id"],
            workspace_path=workspace_path,
            rel_path=args["path"],
            change_summary=args.get("change_summary"),
            created_by=kwargs.get("agent_id"),
        )
    except ArtifactError as e:
        return {"error": str(e)}
    return {
        "artifact_id": artifact.id,
        "revision_id": rev.id,
        "format": artifact.format,
        "path": artifact.current_path,
    }


async def artifact_history(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict:
    """artifact_history(artifact_id) → revisions, newest first."""
    try:
        return {"revisions": await service.history(kwargs["db"], args["artifact_id"])}
    except ArtifactError as e:
        return {"error": str(e)}


async def artifact_restore(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict:
    """artifact_restore(artifact_id, revision_id) → old bytes back as new revision."""
    try:
        rev = await service.restore(
            kwargs["db"],
            args["artifact_id"],
            workspace_path=workspace_path,
            revision_id=args["revision_id"],
            change_summary=args.get("change_summary"),
            **_provenance(kwargs),
        )
    except ArtifactError as e:
        return {"error": str(e)}
    return {"revision_id": rev.id, "revision_number": rev.revision_number}


async def artifact_export_pdf(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict:
    """artifact_export_pdf(artifact_id) → render current revision to PDF."""
    try:
        return await service.export_pdf(
            kwargs["db"],
            args["artifact_id"],
            workspace_path=workspace_path,
            **_provenance(kwargs),
        )
    except ArtifactError as e:
        return {"error": str(e)}

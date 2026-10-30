"""Run filters use existence checks so concurrent calls never duplicate runs."""

from datetime import datetime

from sqlalchemy import JSON, case, cast, exists, func, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.approval import ApprovalRequest
from ..models.artifact import Artifact, ArtifactRevision
from ..models.audit import AuditRecord
from ..models.execution_manifest import ExecutionManifest
from ..models.model_call import ModelCall
from ..models.run import Run
from ..models.schedule import ScheduleOccurrence
from ..models.session import Session
from ..models.terminal import TerminalSession


def filter_runs(
    statement,
    db: AsyncSession,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    purpose: str | None = None,
    kind: str | None = None,
    schedule_id: str | None = None,
    channel: str | None = None,
    capability: str | None = None,
    tool_status: str | None = None,
    effect: str | None = None,
    browser_profile: str | None = None,
    artifact_format: str | None = None,
    retrieval_mode: str | None = None,
    retrieval_degraded: bool | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
):
    """Multiple model predicates must match the same call, not different calls."""
    model_filters = [
        column == value
        for column, value in (
            (ModelCall.provider_id, provider_id),
            (ModelCall.model_name, model),
            (ModelCall.purpose, purpose),
            (ModelCall.kind, kind),
        )
        if value is not None
    ]
    if model_filters:
        statement = statement.where(
            exists(select(ModelCall.id).where(ModelCall.run_id == Run.id, *model_filters))
        )
    if schedule_id is not None:
        statement = statement.where(
            exists(
                select(ScheduleOccurrence.id).where(
                    ScheduleOccurrence.run_id == Run.id,
                    ScheduleOccurrence.schedule_id == schedule_id,
                )
            )
        )
    if channel is not None:
        statement = statement.where(
            exists(
                select(Session.id).where(Session.id == Run.session_id, Session.channel == channel)
            )
        )
    audit_filters = []
    if capability is not None and tool_status not in ("pending_approval", "running"):
        audit_filters.append(AuditRecord.capability_name == capability)
    if tool_status == "pending_approval":
        pending_filters = [
            ApprovalRequest.run_id == Run.id,
            ApprovalRequest.status == "pending",
        ]
        if capability is not None:
            pending_filters.append(ApprovalRequest.capability_name == capability)
        statement = statement.where(exists(select(ApprovalRequest.id).where(*pending_filters)))
    elif tool_status == "running":
        statement = statement.where(
            exists(
                select(TerminalSession.id).where(
                    TerminalSession.run_id == Run.id,
                    TerminalSession.status == "running",
                )
            )
        )
        if capability is not None and capability != "terminal":
            statement = statement.where(False)
    elif tool_status is not None:
        outcome = {"complete": "ok", "failed": "error"}.get(tool_status, tool_status)
        audit_filters.append(AuditRecord.outcome == outcome)
    if effect is not None:
        elements = (
            func.json_each(AuditRecord.effects).table_valued("value")
            if db.get_bind().dialect.name == "sqlite"
            else func.json_array_elements_text(AuditRecord.effects)
            .table_valued("value")
            .render_derived()
        )
        audit_filters.append(exists(select(elements.c.value).where(elements.c.value == effect)))
    if audit_filters:
        statement = statement.where(
            exists(select(AuditRecord.id).where(AuditRecord.run_id == Run.id, *audit_filters))
        )
    dialect = db.get_bind().dialect.name

    def audit_json(column):
        if dialect == "sqlite":
            # Hand-edited/legacy text must not make an entire listing fail.
            return type_coerce(case((func.json_valid(column), column), else_="{}"), JSON)
        return cast(column, JSON)

    if browser_profile is not None:
        statement = statement.where(
            exists(
                select(AuditRecord.id).where(
                    AuditRecord.run_id == Run.id,
                    AuditRecord.capability_name == "browser_open",
                    audit_json(AuditRecord.args)["profile"].as_string() == browser_profile,
                )
            )
            | exists(
                select(ExecutionManifest.id).where(
                    ExecutionManifest.run_id == Run.id,
                    ExecutionManifest.browser_profile_id == browser_profile,
                )
            )
        )
    if artifact_format is not None:
        statement = statement.where(
            exists(
                select(ArtifactRevision.id)
                .join(Artifact, ArtifactRevision.artifact_id == Artifact.id)
                .where(
                    ArtifactRevision.source_run_id == Run.id,
                    Artifact.format == artifact_format,
                )
            )
        )
    if retrieval_mode is not None or retrieval_degraded is not None:
        payload = audit_json(AuditRecord.result)
        retrieval_filters = [
            AuditRecord.run_id == Run.id,
            AuditRecord.capability_name == "doc_search",
        ]
        if retrieval_mode is not None:
            retrieval_filters.append(payload["trace"]["fusion"].as_string() == retrieval_mode)
        if retrieval_degraded is not None:
            array = payload["trace"]["degraded"]
            if dialect == "sqlite":
                retrieval_filters.append(func.json_type(array) == "array")
                length = func.json_array_length(array)
            else:
                valid_array = case(
                    (func.json_typeof(array) == "array", array),
                    else_=cast("[]", JSON),
                )
                retrieval_filters.append(func.json_typeof(array) == "array")
                length = func.json_array_length(valid_array)
            retrieval_filters.append(length > 0 if retrieval_degraded else length == 0)
        statement = statement.where(exists(select(AuditRecord.id).where(*retrieval_filters)))
    if since is not None:
        statement = statement.where(Run.started_at >= since)
    if until is not None:
        statement = statement.where(Run.started_at < until)
    return statement

"""Optional Tools & Runtimes status — readiness only, no installers."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..auth import require_operator
from ..dependencies import get_dependency_registry
from ..runtime_installer import PlanError, get_runtime_installer

router = APIRouter(prefix="/api/dependencies", tags=["dependencies"])


@router.get("")
async def list_dependencies(operator=Depends(require_operator)):
    return {"dependencies": await get_dependency_registry().status()}


@router.post("/recheck")
async def recheck_dependencies(operator=Depends(require_operator)):
    registry = get_dependency_registry()
    registry.clear_cache()
    return {"dependencies": await registry.status(force=True)}


# -- managed install flow (W11) ---------------------------------------------


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dependency_ids: list[str] = Field(min_length=1, max_length=3)


class InstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    consent: Literal[True]


def _raise(err: PlanError):
    from fastapi import HTTPException

    return HTTPException(status_code=err.status, detail=err.detail)


@router.post("/plan")
async def create_plan(body: PlanRequest, operator=Depends(require_operator)):
    try:
        return await get_runtime_installer().plan(body.dependency_ids, operator.id)
    except PlanError as exc:
        raise _raise(exc)


@router.post("/install", status_code=202)
async def start_install(body: InstallRequest, operator=Depends(require_operator)):
    try:
        return await get_runtime_installer().start(body.plan_id, operator.id, body.consent)
    except PlanError as exc:
        raise _raise(exc)


@router.get("/jobs")
async def list_jobs(operator=Depends(require_operator)):
    return {"jobs": get_runtime_installer().list_jobs(operator.id)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, operator=Depends(require_operator)):
    try:
        return get_runtime_installer().get_job(job_id, operator.id)
    except PlanError as exc:
        raise _raise(exc)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, operator=Depends(require_operator)):
    try:
        return await get_runtime_installer().cancel(job_id, operator.id)
    except PlanError as exc:
        raise _raise(exc)

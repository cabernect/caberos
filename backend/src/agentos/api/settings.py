"""Global app settings API — runtime toggles like YOLO mode."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_operator
from ..config import settings
from ..models.operator import Operator

router = APIRouter(prefix="/api/settings", tags=["settings"])


class YoloModeOut(BaseModel):
    yolo_mode: bool


class YoloModeUpdate(BaseModel):
    yolo_mode: bool


@router.get("/yolo")
async def get_yolo_mode(
    operator: Operator = Depends(require_operator),
) -> YoloModeOut:
    return YoloModeOut(yolo_mode=settings.yolo_mode)


@router.put("/yolo")
async def set_yolo_mode(
    req: YoloModeUpdate,
    operator: Operator = Depends(require_operator),
) -> YoloModeOut:
    settings.yolo_mode = req.yolo_mode
    return YoloModeOut(yolo_mode=settings.yolo_mode)

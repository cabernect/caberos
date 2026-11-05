"""Operator speech endpoints (W10) — dictation + read aloud.

These are operator actions, not agent tools: browser cookie/bearer auth,
explicit per-request consent (clicking transcribe/read-aloud IS the egress
consent for that request), bounded inputs, and ledger receipts. No
`media_speak`/`audio_transcribe` capability is registered.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Operator, require_operator
from ..capabilities.bindings import resolve_binding
from ..db import get_db
from ..models.run import Message, Run
from ..speech.renderer import has_speakable_text, render_speakable
from ..speech.service import (
    SPEECH_STT_KEY,
    SPEECH_TTS_KEY,
    STT_MAX_AUDIO_BYTES,
    adapter_for,
    synthesize,
    transcribe,
)

router = APIRouter(prefix="/api/speech", tags=["speech"])

_RATE_WINDOW_S = 60.0
_RATE_MAX = 20
_requests: dict[str, deque[float]] = {"stt": deque(), "tts": deque()}


def _rate_limit(operation: str) -> None:
    now = time.monotonic()
    hits = _requests[operation]
    while hits and now - hits[0] > _RATE_WINDOW_S:
        hits.popleft()
    if len(hits) >= _RATE_MAX:
        raise HTTPException(status_code=429, detail="Too many speech requests — wait a moment.")
    hits.append(now)


async def _status(db: AsyncSession, key: str, operation: str) -> dict:
    resolution = await resolve_binding(db, key)
    provider = resolution.provider
    has_adapter = provider is not None and adapter_for(provider.type, operation) is not None
    reason = resolution.reason
    if resolution.ready and not has_adapter:
        reason = f"Provider type '{provider.type}' does not support {operation} yet."
    return {
        "ready": resolution.ready and has_adapter,
        "configured": resolution.ready,
        "adapter": has_adapter,
        "provider": provider.name if provider else None,
        "provider_type": provider.type if provider else None,
        "model": resolution.binding.model if resolution.binding else "",
        "reason": reason,
    }


@router.get("/status")
async def speech_status(
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {
        "stt": await _status(db, SPEECH_STT_KEY, "stt"),
        "tts": await _status(db, SPEECH_TTS_KEY, "tts"),
    }


class TranscribeOut(BaseModel):
    request_id: str
    transcript: str
    provider: str | None
    model: str
    audio_seconds: float | None


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> TranscribeOut:
    _rate_limit("stt")
    audio = await file.read(STT_MAX_AUDIO_BYTES + 1)
    if len(audio) > STT_MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording exceeds the 15 MiB limit.")
    result, request_id = await transcribe(
        db=db,
        audio=audio,
        mime=file.content_type or "",
    )
    resolution = await resolve_binding(db, SPEECH_STT_KEY)
    return TranscribeOut(
        request_id=request_id,
        transcript=result.text,
        provider=resolution.provider.name if resolution.provider else None,
        model=resolution.binding.model if resolution.binding else "",
        audio_seconds=result.audio_seconds,
    )


class SynthesizeIn(BaseModel):
    message_id: str


@router.post("/synthesize")
async def synthesize_speech(
    body: SynthesizeIn,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """Read-aloud on a persisted assistant message — audio bytes in response.

    Unit 5 swaps this to a workspace artifact response; the operation flow
    (authorize message -> render -> dispatch -> receipt) is already final.
    """
    from fastapi import Response

    _rate_limit("tts")
    message = await db.get(Message, body.message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    if message.role != "assistant":
        raise HTTPException(status_code=422, detail="Only assistant messages can be read aloud.")
    if not has_speakable_text(message.content):
        raise HTTPException(status_code=422, detail="This message has no speakable prose.")
    speakable = render_speakable(message.content)

    run = await db.get(Run, message.run_id)
    result, request_id = await synthesize(
        db=db,
        text=speakable,
        session_id=run.session_id if run else None,
        agent_id=run.agent_id if run else None,
        message_id=message.id,
    )
    return Response(
        content=result.audio,
        media_type=result.mime,
        headers={"X-Speech-Request-Id": request_id},
    )

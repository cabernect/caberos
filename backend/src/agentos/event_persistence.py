"""Run event persistence — turns harness/pipeline events into Message rows.

The pipeline wraps its SSE emitter with :class:`RunEventPersister` so that
thinking chunks, intermediate narration, and tool-call outcomes survive
``message_complete`` reloads as conversation history. Seq numbers are
monotonic per run (user message is seq=0, so this starts at 1) and
sub-agent events get separate buffers persisted with ``subagent_id`` set.

All database access goes through ``db_lock`` — the same lock the run's
``SyscallHandler`` uses for tool writes — because parallel tool calls can
emit events concurrently and SQLAlchemy sessions are not safe for
concurrent commits.
"""

import asyncio
import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models.run import Message, Run

logger = logging.getLogger(__name__)

_TERMINAL_TOOL_STATUSES = ("complete", "denied", "failed", "timeout", "interrupted")


class RunEventPersister:
    """Persist run events as Messages; forward them to the SSE emitter.

    ``emit(event_type, payload)`` returns a receipt
    ``{assistant_message_id, tool_message_id}`` when a tool outcome was
    persisted, else ``None``. Receipts are cached per call id — duplicate
    terminal emissions return the same ids.
    """

    def __init__(
        self,
        db: AsyncSession,
        run: Run,
        *,
        event_emitter: Any = None,
        agent_id: str,
        session_id: str,
        db_lock: asyncio.Lock | None = None,
    ) -> None:
        self._db = db
        self._run = run
        self._forward = event_emitter
        self._agent_id = agent_id
        self._session_id = session_id
        self.db_lock = db_lock if db_lock is not None else asyncio.Lock()
        self._msg_seq = 1  # user message is seq=0
        self._thinking_buffers: dict[str | None, list[str]] = {None: []}
        self._token_buffers: dict[str | None, list[str]] = {None: []}
        self._tool_calls_seen: set[str] = set()
        self._tool_call_receipts: dict[str, dict] = {}
        # Narration row id for the current tool batch, per scope — flushed
        # at the first tool_call event, read when each call's terminal
        # receipt is built.
        self._narration_ids: dict[str | None, str] = {}

    @property
    def next_seq(self) -> int:
        """Next unused seq — the final assistant message takes this slot."""
        return self._msg_seq

    async def emit(self, event_type: str, payload: dict) -> dict | None:
        async with self.db_lock:
            return await self._emit(event_type, payload)

    async def _emit(self, event_type: str, payload: dict) -> dict | None:
        # Forward to the real emitter (SSE broadcast)
        if self._forward:
            result_emit = self._forward(event_type, payload)
            if hasattr(result_emit, "__await__"):
                await result_emit

        # Determine which buffer set to use (parent vs sub-agent)
        sub_id = payload.get("subagent_id")
        if sub_id not in self._thinking_buffers:
            self._thinking_buffers[sub_id] = []
        if sub_id not in self._token_buffers:
            self._token_buffers[sub_id] = []
        tb = self._thinking_buffers[sub_id]
        tkb = self._token_buffers[sub_id]

        receipt = None
        tool_message_id: str | None = None

        # Persist thinking as a single Message when it's done
        # (we buffer chunks and flush on first token/tool_call)
        if event_type == "thinking":
            tb.append(payload.get("content", ""))

        # Buffer text tokens — these are intermediate narration that
        # the model produces before tool calls. We flush them as an
        # assistant message when a tool_call arrives.
        if event_type == "token":
            tkb.append(payload.get("content", ""))

        # Flush thinking buffer on first token/tool_call
        if event_type in ("token", "tool_call") and tb:
            # Flush buffered thinking into one Message row
            thinking_text = "".join(tb)
            tb.clear()
            if thinking_text:
                self._db.add(
                    Message(
                        id=str(uuid.uuid4()),
                        run_id=self._run.id,
                        role="thinking",
                        content=thinking_text,
                        seq=self._msg_seq,
                        subagent_id=sub_id,
                    )
                )
                self._msg_seq += 1
                await self._db.commit()

        # Flush token buffer when a tool_call arrives — the model
        # produced narration text before the tool call, save it
        # as an assistant message so it survives message_complete reload.
        if event_type == "tool_call" and tkb:
            text_content = "".join(tkb)
            tkb.clear()
            if text_content.strip():
                narration_msg = Message(
                    id=str(uuid.uuid4()),
                    run_id=self._run.id,
                    role="assistant",
                    content=text_content,
                    seq=self._msg_seq,
                    subagent_id=sub_id,
                )
                self._db.add(narration_msg)
                self._msg_seq += 1
                await self._db.commit()
                self._narration_ids[sub_id] = narration_msg.id

        # Persist tool_call events (only on final status to avoid duplicates)
        if event_type == "tool_call":
            tc_id = payload.get("id", "")
            status = payload.get("status", "")
            # Store the final state as a Message — every terminal
            # outcome, not just complete/denied.
            if tc_id in self._tool_call_receipts:
                return self._tool_call_receipts[tc_id]
            if status in _TERMINAL_TOOL_STATUSES and tc_id not in self._tool_calls_seen:
                self._tool_calls_seen.add(tc_id)
                tool_msg = Message(
                    id=str(uuid.uuid4()),
                    run_id=self._run.id,
                    role="tool_call",
                    content=json.dumps(
                        {
                            "id": tc_id,
                            "capability": payload.get("capability", ""),
                            "args": payload.get("args", {}),
                            "status": status,
                            "result": payload.get("result"),
                            "denied_reason": payload.get("reason"),
                            "approval_id": payload.get("approval_id"),
                            "approval_batch_id": payload.get("approval_batch_id"),
                            "approval_batch_size": payload.get("approval_batch_size"),
                        }
                    ),
                    seq=self._msg_seq,
                    subagent_id=sub_id,
                )
                self._db.add(tool_msg)
                self._msg_seq += 1
                await self._db.commit()
                tool_message_id = tool_msg.id
                receipt = {
                    "assistant_message_id": self._narration_ids.get(sub_id),
                    "tool_message_id": tool_message_id,
                }
                self._tool_call_receipts[tc_id] = receipt

        # Clear token buffer on guardrail correction — the corrected
        # content will be saved as the final assistant message.
        if event_type == "turn_complete":
            # Batch narration id is per-turn — a later tool batch
            # must not claim this turn's narration row.
            self._narration_ids.pop(sub_id, None)

        if event_type == "guardrail_correction":
            tkb.clear()

        # A parked approval flips the run to awaiting_approval so the
        # operator can discover it — persist it here (not in the
        # transport layer) so scheduled/channel runs behave the same.
        if event_type == "tool_call" and payload.get("status") == "pending_approval":
            self._run.status = "awaiting_approval"
            await self._db.commit()
            asyncio.create_task(self._notify_approval_required(payload))

        return receipt

    async def _notify_approval_required(self, payload: dict) -> None:
        try:
            from .db import async_session_factory
            from .notifications import call_brief, create_notification

            async with async_session_factory() as ndb:
                await create_notification(
                    ndb,
                    notification_type="approval_required",
                    severity="warning",
                    title="Approval required",
                    message=(f"Waiting to run {call_brief(payload)}."),
                    action_path=(f"/agents/{self._agent_id}/chat?session={self._session_id}"),
                    entity_id=self._run.id,
                    entity_type="run",
                    agent_id=self._agent_id,
                )
                await ndb.commit()
        except Exception:
            logger.debug("approval_required notification failed", exc_info=True)

"""Pipeline — D19's 13-step execution orchestrator.

This is the heart of the system. Both channels (plan 08) and the heartbeat
scheduler (plan 12) call pipeline.handle_inbound() to trigger a run.
The pipeline is channel-agnostic.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .agent_service import get_active_config
from .capabilities.builtin import register_builtin_capabilities
from .harness.guardrails import apply_input_guardrails
from .harness.loop import Harness, RunResult
from .models.contact import Contact
from .models.run import Message, Run
from .models.session import Session
from .sandbox.workspace import WorkspaceManager
from .syscall.lock import session_locks
from .syscall.mediator import SyscallHandler


async def _generate_session_title(
    db: AsyncSession,
    agent_config: Any,
    user_message: str,
    assistant_response: str,
) -> str | None:
    """Generate a short title for the session using the LLM.

    Returns a 3-5 word title, or None if generation fails.
    Uses the same model/provider as the agent, with a cheap 1-turn call.
    """
    try:
        from .harness.litellm_adapter import LiteLLMAdapter

        adapter = LiteLLMAdapter(db)
        prompt = (
            f"Summarize this conversation in 3-5 words. "
            f"Output ONLY the title, no quotes, no punctuation at the end.\n\n"
            f"User: {user_message[:200]}\n"
            f"Assistant: {assistant_response[:200]}"
        )
        response = await adapter.complete(
            agent_model=agent_config.model,
            messages=[{"role": "user", "content": prompt}],
            tools=None,
        )
        title = response.content.strip().strip('"').strip("'")[:60]
        return title if title else None
    except Exception:
        return None


async def _generate_session_title_from_history(
    db: AsyncSession,
    agent_config: Any,
    messages: list,
) -> str | None:
    """Generate a short title from the full conversation history.

    Uses up to the last 6 user+assistant messages for context.
    Returns a 3-5 word title, or None if generation fails.
    """
    try:
        from .harness.litellm_adapter import LiteLLMAdapter

        # Extract user and assistant messages only
        convo = []
        for msg in messages:
            if msg.role in ("user", "assistant") and msg.content:
                convo.append(f"{msg.role.capitalize()}: {msg.content[:150]}")
            if len(convo) >= 6:
                break

        if not convo:
            return None

        adapter = LiteLLMAdapter(db)
        prompt = (
            f"Summarize this conversation in 3-5 words. "
            f"Output ONLY the title, no quotes, no punctuation at the end.\n\n"
            + "\n".join(convo)
        )
        response = await adapter.complete(
            agent_model=agent_config.model,
            messages=[{"role": "user", "content": prompt}],
            tools=None,
        )
        title = response.content.strip().strip('"').strip("'")[:60]
        return title if title else None
    except Exception:
        return None


@dataclass
class Attachment:
    """A multimodal attachment on a user message (image, URL, or workspace file).

    For images: type="image", data is base64-encoded with mime type
        → sent to the model as {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    For URLs: type="url", data is the URL
        → sent to the model as {"type": "image_url", "image_url": {"url": "https://..."}}
        (the model fetches and processes the URL)
    For workspace files: type="file", data is the file content (text or base64)
        → text files are appended to the message; images are sent as image_url
    """

    type: str  # "image", "url", "file"
    mime_type: str  # e.g. "image/png", "text/plain", "application/pdf"
    data: str  # base64 for images, URL for urls, text content for files
    filename: str = ""  # original filename (for display + audit)


@dataclass
class InboundMessage:
    """Normalized inbound message (produced by channels, consumed by pipeline)."""

    channel: str  # "dashboard_chat", "heartbeat", ...
    bot_id: str  # agent_id
    external_user_id: str
    text: str
    message_id: str  # dedup key
    is_test: bool = False
    model_override: dict[str, str] | None = None  # {provider_id, name} or None
    session_id: str | None = None  # explicit session to use, else auto-resume
    new_session: bool = False  # if true, force create a new session (ignore auto-resume)
    attachments: list[Attachment] = None  # multimodal attachments (images, URLs, files)


# Ensure capabilities are registered
_capabilities_registered = False


def _ensure_capabilities() -> None:
    global _capabilities_registered
    if not _capabilities_registered:
        register_builtin_capabilities()
        _capabilities_registered = True


class Pipeline:
    """The 13-step execution pipeline (D19)."""

    def __init__(self, db: AsyncSession, harness: Harness) -> None:
        self.db = db
        self.harness = harness
        _ensure_capabilities()

    async def handle_inbound(
        self,
        message: InboundMessage,
        trigger: str = "user_message",
        is_test: bool = False,
        event_emitter: Any = None,
    ) -> Run:
        """Execute D19's 13-step pipeline for an inbound message."""

        # Step 2: Deduplicate
        existing = await self.db.execute(select(Run).where(Run.message_id == message.message_id))
        if existing.scalar_one_or_none() is not None:
            # Already seen — acknowledge and drop
            return existing.scalar_one()  # type: ignore

        # Step 4: Resolve Contact (before creating Run, so FK is valid)
        contact = await self._resolve_contact(message)

        # Step 5: Resolve Session (use explicit session_id if provided, else auto-resume)
        session = await self._resolve_session(
            contact.id, message.bot_id, message.session_id, message.new_session
        )

        # Step 3: Persist and acknowledge — create Run row with valid FKs
        run = Run(
            id=str(uuid.uuid4()),
            session_id=session.id,
            contact_id=contact.id,
            agent_id=message.bot_id,
            status="pending",
            trigger=trigger,
            message_id=message.message_id,
            is_test=is_test or message.is_test,
        )
        self.db.add(run)
        await self.db.flush()

        # Emit run_started after the run is created so we have the run_id
        # (needed for run manager to register the RunContext before any other events fire)
        if event_emitter:
            result_emit = event_emitter(
                "run_started",
                {"run_id": run.id, "session_id": session.id, "agent_id": message.bot_id},
            )
            if hasattr(result_emit, "__await__"):
                await result_emit

        # Apply input guardrails — redact secrets, detect prompt injection (D2)
        input_guardrail = apply_input_guardrails(message.text)
        guardrailed_text = input_guardrail.content

        # Emit input guardrail warnings (if any) so the operator sees them live
        if input_guardrail.warnings and event_emitter:
            result_emit = event_emitter(
                "guardrail_warning",
                {"warnings": input_guardrail.warnings, "direction": "input"},
            )
            if hasattr(result_emit, "__await__"):
                await result_emit

        # Store the user message (with secrets redacted, if any)
        # Persist attachment metadata (not the base64 data — too large for SQLite)
        import json as _json

        attachment_meta = None
        if message.attachments:
            attachment_meta = _json.dumps([
                {
                    "type": a.type,
                    "mime_type": a.mime_type,
                    "filename": a.filename,
                }
                for a in message.attachments
            ])

        user_msg = Message(
            id=str(uuid.uuid4()),
            run_id=run.id,
            role="user",
            content=guardrailed_text,
            seq=0,
            attachments=attachment_meta,
        )
        self.db.add(user_msg)
        await self.db.flush()

        # Set a temporary title from the first user message if untitled.
        # This gets replaced with an LLM-generated title 3 minutes after
        # the session starts (see title check below).
        if not session.title:
            session.title = guardrailed_text[:60].strip() or "New conversation"
            await self.db.flush()

        # Commit the initial writes (run, user message, session title)
        # so the SQLite write lock is released before the long-running
        # harness loop starts. Without this, the write lock is held for
        # the entire run duration, blocking all other DB operations.
        await self.db.commit()

        # Step 6: Serialize — acquire per-Session lock
        # Different sessions for the same agent run concurrently.
        # Same session serializes (don't interleave turns in one conversation).
        lock = session_locks.get_lock(session.id)
        async with lock:
            run.status = "running"
            run.started_at = datetime.now(UTC)
            await self.db.flush()

            try:
                # Step 7: Assemble context — get agent config
                agent_config = await get_active_config(self.db, message.bot_id)
                if agent_config is None:
                    raise ValueError(f"Agent {message.bot_id} not found or has no active config")

                # Apply model override if provided (user can switch models per-message)
                if message.model_override:
                    from .config_schema import ModelConfig as MC

                    agent_config = agent_config.model_copy(deep=True)
                    agent_config.model = MC(
                        provider_id=message.model_override["provider_id"],
                        name=message.model_override["name"],
                        max_tokens=agent_config.model.max_tokens,
                    )

                # Guard: refuse to run if no model is configured (and not a test run).
                # This happens when a provider is deleted out from under an agent.
                if not message.is_test and not agent_config.model.is_configured:
                    raise ValueError(
                        "No model configured for this agent. "
                        "Add a provider in Settings → Providers, then assign a model."
                    )

                # Get recent messages from this session (last 10)
                # Exclude the current run — its user message is appended
                # separately by build_message_history to avoid duplication.
                recent_msgs = await self._get_recent_messages(
                    session.id, limit=10, exclude_run_id=run.id
                )

                # Set up workspace
                wm = WorkspaceManager()
                workspace_path = wm.create_workspace(message.bot_id)
                if agent_config.workspace:
                    workspace_path = agent_config.workspace
                else:
                    agent_config.workspace = str(workspace_path)

                # Set up syscall handler
                syscall_handler = SyscallHandler(
                    db=self.db,
                    workspace_path=str(workspace_path),
                    sandbox_mode=agent_config.sandbox_mode,
                )

                # Wrap event_emitter to persist thinking, intermediate text, and
                # tool_call events as Message rows, so they show up in conversation
                # history. Uses a monotonically increasing seq counter to guarantee
                # correct ordering: thinking → text → tool_call → assistant.
                # Sub-agent events (tagged with subagent_id) get separate buffers
                # and are persisted with subagent_id set on the Message.
                _thinking_buffers: dict[str | None, list[str]] = {None: []}
                _token_buffers: dict[str | None, list[str]] = {None: []}
                _tool_calls_seen: set[str] = set()
                _msg_seq = 1  # user message is seq=0

                async def _persisting_emitter(event_type: str, payload: dict) -> None:
                    nonlocal _msg_seq

                    # Forward to the real emitter (SSE broadcast)
                    if event_emitter:
                        result_emit = event_emitter(event_type, payload)
                        if hasattr(result_emit, "__await__"):
                            await result_emit

                    # Determine which buffer set to use (parent vs sub-agent)
                    sub_id = payload.get("subagent_id")
                    if sub_id not in _thinking_buffers:
                        _thinking_buffers[sub_id] = []
                    if sub_id not in _token_buffers:
                        _token_buffers[sub_id] = []
                    _tb = _thinking_buffers[sub_id]
                    _tkb = _token_buffers[sub_id]

                    # Persist thinking as a single Message when it's done
                    # (we buffer chunks and flush on first token/tool_call)
                    if event_type == "thinking":
                        _tb.append(payload.get("content", ""))

                    # Buffer text tokens — these are intermediate narration that
                    # the model produces before tool calls. We flush them as an
                    # assistant message when a tool_call arrives.
                    if event_type == "token":
                        _tkb.append(payload.get("content", ""))

                    # Flush thinking buffer on first token/tool_call
                    if event_type in ("token", "tool_call") and _tb:
                        # Flush buffered thinking into one Message row
                        thinking_text = "".join(_tb)
                        _tb.clear()
                        if thinking_text:
                            self.db.add(
                                Message(
                                    id=str(uuid.uuid4()),
                                    run_id=run.id,
                                    role="thinking",
                                    content=thinking_text,
                                    seq=_msg_seq,
                                    subagent_id=sub_id,
                                )
                            )
                            _msg_seq += 1
                            await self.db.commit()

                    # Flush token buffer when a tool_call arrives — the model
                    # produced narration text before the tool call, save it
                    # as an assistant message so it survives message_complete reload.
                    if event_type == "tool_call" and _tkb:
                        text_content = "".join(_tkb)
                        _tkb.clear()
                        if text_content.strip():
                            self.db.add(
                                Message(
                                    id=str(uuid.uuid4()),
                                    run_id=run.id,
                                    role="assistant",
                                    content=text_content,
                                    seq=_msg_seq,
                                    subagent_id=sub_id,
                                )
                            )
                            _msg_seq += 1
                            await self.db.commit()

                    # Persist tool_call events (only on final status to avoid duplicates)
                    if event_type == "tool_call":
                        tc_id = payload.get("id", "")
                        status = payload.get("status", "")
                        # Store the final state (complete/denied) as a Message
                        if status in ("complete", "denied") and tc_id not in _tool_calls_seen:
                            _tool_calls_seen.add(tc_id)
                            import json as _json
                            self.db.add(
                                Message(
                                    id=str(uuid.uuid4()),
                                    run_id=run.id,
                                    role="tool_call",
                                    content=_json.dumps({
                                        "id": tc_id,
                                        "capability": payload.get("capability", ""),
                                        "args": payload.get("args", {}),
                                        "status": status,
                                        "result": payload.get("result"),
                                    }),
                                    seq=_msg_seq,
                                    subagent_id=sub_id,
                                )
                            )
                            _msg_seq += 1
                            await self.db.commit()

                    # Clear token buffer on guardrail correction — the corrected
                    # content will be saved as the final assistant message.
                    if event_type == "guardrail_correction":
                        _tkb.clear()

                # Steps 8-11: Run the harness (with guardrailed user message + attachments)
                result: RunResult = await self.harness.run(
                    agent_config=agent_config,
                    session=session,
                    message=guardrailed_text,
                    syscall_handler=syscall_handler,
                    run_id=run.id,
                    recent_messages=recent_msgs,
                    trigger=trigger,
                    event_emitter=_persisting_emitter,
                    attachments=message.attachments,
                )

                # Store the assistant's response
                assistant_msg = Message(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    role="assistant" if trigger == "user_message" else "heartbeat",
                    content=result.final_answer,
                    seq=_msg_seq,
                )
                self.db.add(assistant_msg)

                # Step 13: Record — close the Run
                run.status = result.status
                run.tokens_in = result.tokens_in
                run.tokens_out = result.tokens_out
                run.cost = result.total_cost
                run.completed_at = datetime.now(UTC)
                if result.error:
                    run.error = result.error

                # Update session activity
                session.last_activity_at = datetime.now(UTC)

                # Generate LLM-based session title 3 minutes after the session
                # started. This avoids locking in a title from a "nothing" first
                # message (e.g. "hello") — by 3 min there's usually a real conversation.
                if result.final_answer and session.title:
                    started = session.started_at
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=UTC)
                    session_age = (datetime.now(UTC) - started).total_seconds()
                    if session_age >= 180:  # 3 minutes
                        # Gather all user + assistant messages for a better title
                        all_msgs = await self._get_recent_messages(session.id, limit=20)
                        llm_title = await _generate_session_title_from_history(
                            self.db, agent_config, all_msgs
                        )
                        if llm_title:
                            session.title = llm_title

                await self.db.commit()

            except Exception as e:
                # Pipeline exception — mark run as failed
                run.status = "failed"
                run.error = str(e)
                run.completed_at = datetime.now(UTC)
                await self.db.commit()
                raise

        return run

    async def _resolve_contact(self, message: InboundMessage) -> Contact:
        """Step 4: Look up or create a Contact by (channel, bot_id, external_user_id)."""
        result = await self.db.execute(
            select(Contact).where(
                Contact.channel == message.channel,
                Contact.bot_id == message.bot_id,
                Contact.external_user_id == message.external_user_id,
            )
        )
        contact = result.scalar_one_or_none()
        if contact is None:
            contact = Contact(
                id=str(uuid.uuid4()),
                channel=message.channel,
                bot_id=message.bot_id,
                external_user_id=message.external_user_id,
                display_name=message.external_user_id,
            )
            self.db.add(contact)
            await self.db.flush()
        return contact

    async def _resolve_session(
        self,
        contact_id: str,
        agent_id: str,
        explicit_session_id: str | None = None,
        new_session: bool = False,
    ) -> Session:
        """Step 5: Resume the live session or open one.

        If explicit_session_id is provided, use that session (must belong to
        this contact+agent). If new_session is True, skip auto-resume and create
        a fresh session. Otherwise, resume the most recent active session or
        create a new one.
        """
        if explicit_session_id:
            result = await self.db.execute(
                select(Session).where(
                    Session.id == explicit_session_id,
                    Session.contact_id == contact_id,
                    Session.agent_id == agent_id,
                )
            )
            session = result.scalar_one_or_none()
            if session is not None:
                return session
            # Fall through to auto-resume if session not found

        # Skip auto-resume if new_session is requested
        if not new_session:
            result = await self.db.execute(
                select(Session)
                .where(
                    Session.contact_id == contact_id,
                    Session.agent_id == agent_id,
                    Session.status == "active",
                )
                .order_by(Session.last_activity_at.desc())
            )
            session = result.scalars().first()
            if session is not None:
                return session

        session = Session(
            id=str(uuid.uuid4()),
            contact_id=contact_id,
            agent_id=agent_id,
            status="active",
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def _get_recent_messages(
        self, session_id: str, limit: int = 10, exclude_run_id: str | None = None
    ) -> list[Message]:
        """Get recent messages from the session for context.

        exclude_run_id: if set, skip messages from this run (e.g. the current
        run's user message, which is appended separately by build_message_history).
        """
        stmt = (
            select(Message)
            .join(Run, Message.run_id == Run.id)
            .where(Run.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        if exclude_run_id:
            stmt = stmt.where(Message.run_id != exclude_run_id)
        result = await self.db.execute(stmt)
        msgs = list(result.scalars().all())
        msgs.reverse()  # chronological order
        return msgs

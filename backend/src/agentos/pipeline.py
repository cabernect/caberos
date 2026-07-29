"""Pipeline — D19's 13-step execution orchestrator.

This is the heart of the system. Both channels (plan 08) and the heartbeat
scheduler (plan 12) call pipeline.handle_inbound() to trigger a run.
The pipeline is channel-agnostic.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .agent_service import get_active_config
from .capabilities.builtin import register_builtin_capabilities
from .harness.loop import Harness, RunResult
from .models.contact import Contact
from .models.run import Message, Run
from .models.session import Session
from .sandbox.workspace import WorkspaceManager
from .syscall.lock import contact_locks
from .syscall.mediator import SyscallHandler


@dataclass
class InboundMessage:
    """Normalized inbound message (produced by channels, consumed by pipeline)."""

    channel: str  # "dashboard_chat", "heartbeat", ...
    bot_id: str  # agent_id
    external_user_id: str
    text: str
    message_id: str  # dedup key
    is_test: bool = False


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
    ) -> Run:
        """Execute D19's 13-step pipeline for an inbound message."""

        # Step 2: Deduplicate
        existing = await self.db.execute(select(Run).where(Run.message_id == message.message_id))
        if existing.scalar_one_or_none() is not None:
            # Already seen — acknowledge and drop
            return existing.scalar_one()  # type: ignore

        # Step 4: Resolve Contact (before creating Run, so FK is valid)
        contact = await self._resolve_contact(message)

        # Step 5: Resolve Session
        session = await self._resolve_session(contact.id, message.bot_id)

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

        # Store the user message
        user_msg = Message(
            id=str(uuid.uuid4()),
            run_id=run.id,
            role="user",
            content=message.text,
        )
        self.db.add(user_msg)
        await self.db.flush()

        # Step 6: Serialize — acquire per-Contact lock
        lock = contact_locks.get_lock(contact.id)
        async with lock:
            run.status = "running"
            run.started_at = datetime.now(UTC)
            await self.db.flush()

            try:
                # Step 7: Assemble context — get agent config
                agent_config = await get_active_config(self.db, message.bot_id)
                if agent_config is None:
                    raise ValueError(f"Agent {message.bot_id} not found or has no active config")

                # Get recent messages from this session (last 10)
                recent_msgs = await self._get_recent_messages(session.id, limit=10)

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
                )

                # Steps 8-11: Run the harness
                result: RunResult = await self.harness.run(
                    agent_config=agent_config,
                    session=session,
                    message=message.text,
                    syscall_handler=syscall_handler,
                    run_id=run.id,
                    recent_messages=recent_msgs,
                    trigger=trigger,
                )

                # Store the assistant's response
                assistant_msg = Message(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    role="assistant" if trigger == "user_message" else "heartbeat",
                    content=result.final_answer,
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

    async def _resolve_session(self, contact_id: str, agent_id: str) -> Session:
        """Step 5: Resume the live session or open one."""
        result = await self.db.execute(
            select(Session)
            .where(
                Session.contact_id == contact_id,
                Session.agent_id == agent_id,
                Session.status == "active",
            )
            .order_by(Session.last_activity_at.desc())
        )
        session = result.scalar_one_or_none()
        if session is None:
            session = Session(
                id=str(uuid.uuid4()),
                contact_id=contact_id,
                agent_id=agent_id,
                status="active",
            )
            self.db.add(session)
            await self.db.flush()
        return session

    async def _get_recent_messages(self, session_id: str, limit: int = 10) -> list[Message]:
        """Get recent messages from the session for context."""
        result = await self.db.execute(
            select(Message)
            .join(Run, Message.run_id == Run.id)
            .where(Run.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        msgs = list(result.scalars().all())
        msgs.reverse()  # chronological order
        return msgs

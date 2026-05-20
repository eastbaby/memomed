from typing import Literal

from sqlalchemy import select, update

from app.agent.api.schemas import AgentEvent, AgentRunResult
from app.db import AsyncSessionLocal
from app.models.models import MmAgentConversation, MmAgentEvent, MmAgentRun


TriggerType = Literal["user_message", "resume_interrupt", "background_job"]


async def persist_run_result(
    result: AgentRunResult,
    *,
    trigger_type: TriggerType,
    owner_user_id: str = "default",
) -> None:
    """Persist the product-facing event timeline for one agent run."""
    if not result.events:
        return

    run_id = result.events[0].run_id or f"run_{result.thread_id}"
    title = _title_from_events(result.events)
    run_status = _run_status_from_result(result)

    async with AsyncSessionLocal() as session:
        existing_conversation = await session.get(MmAgentConversation, result.thread_id)
        seq_offset = existing_conversation.last_event_seq if existing_conversation else 0
        last_event_seq = seq_offset + max(event.seq for event in result.events)
        await session.merge(
            MmAgentConversation(
                id=result.thread_id,
                owner_user_id=owner_user_id,
                title=existing_conversation.title if existing_conversation and existing_conversation.title else title,
                status="active",
                langgraph_thread_id=result.thread_id,
                last_event_seq=last_event_seq,
            )
        )
        await session.merge(
            MmAgentRun(
                id=run_id,
                conversation_id=result.thread_id,
                owner_user_id=owner_user_id,
                trigger_type=trigger_type,
                status=run_status,
                error=result.error,
                run_metadata={},
            )
        )

        if trigger_type == "resume_interrupt":
            await session.execute(_pending_interrupt_completion_statement(result.thread_id, owner_user_id))

        for event in result.events:
            await session.merge(_event_model(event, result.thread_id, run_id, owner_user_id, seq_offset=seq_offset))

        await session.commit()


async def list_conversations(owner_user_id: str = "default") -> list[MmAgentConversation]:
    async with AsyncSessionLocal() as session:
        statement = (
            select(MmAgentConversation)
            .where(MmAgentConversation.owner_user_id == owner_user_id)
            .where(MmAgentConversation.status == "active")
            .order_by(MmAgentConversation.updated_at.desc())
        )
        return list((await session.execute(statement)).scalars().all())


async def list_events(
    conversation_id: str,
    *,
    owner_user_id: str = "default",
    after_seq: int = 0,
    limit: int = 100,
) -> list[AgentEvent]:
    async with AsyncSessionLocal() as session:
        statement = (
            select(MmAgentEvent)
            .where(MmAgentEvent.owner_user_id == owner_user_id)
            .where(MmAgentEvent.conversation_id == conversation_id)
            .where(MmAgentEvent.seq > after_seq)
            .order_by(MmAgentEvent.seq.asc())
            .limit(limit)
        )
        rows = (await session.execute(statement)).scalars().all()
        return [_event_response(row) for row in rows]


async def get_last_event_seq(conversation_id: str, owner_user_id: str = "default") -> int:
    async with AsyncSessionLocal() as session:
        conversation = await session.get(MmAgentConversation, conversation_id)
        if not conversation or conversation.owner_user_id != owner_user_id:
            return 0
        return int(conversation.last_event_seq or 0)


def apply_conversation_seq_offset(result: AgentRunResult, *, seq_offset: int) -> AgentRunResult:
    shifted = result.model_copy(deep=True)
    for event in shifted.events:
        event.seq = seq_offset + event.seq
    return shifted


def _title_from_events(events: list[AgentEvent]) -> str:
    for event in events:
        if event.event_type == "message.user" and event.content:
            return event.content[:80]
    return "新的健康咨询"


def _run_status_from_result(result: AgentRunResult) -> str:
    if result.status == "interrupted":
        return "interrupted"
    if result.status == "error":
        return "failed"
    return "completed"


def _event_model(
    event: AgentEvent,
    conversation_id: str,
    run_id: str,
    owner_user_id: str,
    *,
    seq_offset: int = 0,
) -> MmAgentEvent:
    payload = event.payload or {}
    return MmAgentEvent(
        id=event.id,
        conversation_id=conversation_id,
        turn_id=event.turn_id,
        run_id=run_id,
        work_item_id=event.work_item_id,
        work_item_type=event.work_item_type,
        owner_user_id=owner_user_id,
        seq=seq_offset + event.seq,
        event_type=event.event_type,
        role=event.role,
        visibility=event.visibility,
        status=event.status,
        parent_event_id=event.parent_event_id,
        dedupe_key=event.dedupe_key,
        title=event.title,
        content=event.content,
        payload=payload,
    )


def _pending_interrupt_completion_statement(conversation_id: str, owner_user_id: str):
    return (
        update(MmAgentEvent)
        .where(MmAgentEvent.conversation_id == conversation_id)
        .where(MmAgentEvent.owner_user_id == owner_user_id)
        .where(MmAgentEvent.event_type == "interrupt.requested")
        .where(MmAgentEvent.status == "pending")
        .values(status="completed")
    )


def _event_response(row: MmAgentEvent) -> AgentEvent:
    return AgentEvent(
        id=row.id,
        conversation_id=row.conversation_id,
        turn_id=row.turn_id,
        run_id=row.run_id,
        work_item_id=row.work_item_id,
        work_item_type=row.work_item_type,
        seq=row.seq,
        event_type=row.event_type,
        role=row.role,
        visibility=row.visibility,
        status=row.status,
        parent_event_id=row.parent_event_id,
        dedupe_key=row.dedupe_key,
        title=row.title,
        content=row.content,
        payload=row.payload or {},
    )

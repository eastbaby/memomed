from typing import Literal

from sqlalchemy import func, select, update

from app.agent.api.schemas import AgentEvent, AgentRunResult
from app.db import AsyncSessionLocal
from app.models.models import MmAgentConversation, MmAgentEvent, MmAgentRun


TriggerType = Literal["user_message", "resume_interrupt", "background_job"]


async def persist_run_result(
    result: AgentRunResult,
    *,
    trigger_type: TriggerType,
    owner_user_id: str = "default",
) -> AgentRunResult:
    """Persist the product-facing event timeline for one agent run."""
    if not result.events:
        return result

    run_id = result.events[0].run_id
    if not run_id:
        raise ValueError("Agent run result events must include run_id before persistence.")
    title = _title_from_events(result.events)
    run_status = _run_status_from_result(result)

    async with AsyncSessionLocal() as session:
        await session.execute(_conversation_seq_lock_statement(result.thread_id))
        existing_conversation = (
            await session.execute(_conversation_for_update_statement(result.thread_id))
        ).scalar_one_or_none()
        seq_offset = existing_conversation.last_event_seq if existing_conversation else 0
        persisted_result = assign_conversation_seq(result, seq_offset=seq_offset)
        persisted_events = persisted_result.events
        last_event_seq = max(event.seq for event in persisted_events if event.seq is not None)
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

        for event in persisted_events:
            await session.merge(_event_model(event, result.thread_id, run_id, owner_user_id))

        await session.commit()
        return persisted_result


def _conversation_seq_lock_statement(conversation_id: str):
    return select(func.pg_advisory_xact_lock(func.hashtext(conversation_id)))


def _conversation_for_update_statement(conversation_id: str):
    return select(MmAgentConversation).where(MmAgentConversation.id == conversation_id).with_for_update()


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


def assign_conversation_seq(result: AgentRunResult, *, seq_offset: int) -> AgentRunResult:
    shifted = result.model_copy(deep=True)
    ordinals = [event.ordinal for event in shifted.events]
    if sorted(ordinals) != list(range(1, len(ordinals) + 1)):
        raise ValueError("Agent run events must have contiguous 1-based ordinal values.")
    for index, event in enumerate(shifted.events, start=1):
        event.seq = seq_offset + index
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
) -> MmAgentEvent:
    if event.seq is None:
        raise ValueError("Agent event must have conversation seq before persistence.")
    payload = {**(event.payload or {}), "ordinal": event.ordinal}
    return MmAgentEvent(
        id=event.id,
        conversation_id=conversation_id,
        turn_id=event.turn_id,
        run_id=run_id,
        work_item_id=event.work_item_id,
        work_item_type=event.work_item_type,
        owner_user_id=owner_user_id,
        seq=event.seq,
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
    payload = row.payload or {}
    return AgentEvent(
        id=row.id,
        conversation_id=row.conversation_id,
        turn_id=row.turn_id,
        run_id=row.run_id,
        work_item_id=row.work_item_id,
        work_item_type=row.work_item_type,
        ordinal=int(payload["ordinal"]),
        seq=row.seq,
        event_type=row.event_type,
        role=row.role,
        visibility=row.visibility,
        status=row.status,
        parent_event_id=row.parent_event_id,
        dedupe_key=row.dedupe_key,
        title=row.title,
        content=row.content,
        payload=payload,
    )

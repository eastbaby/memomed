from fastapi import APIRouter, HTTPException

from app.agent.api.schemas import (
    AgentRunResult,
    ChatRequest,
    ConversationResponse,
    EventHistoryResponse,
    ResumeRequest,
)
from app.agent.events.service import list_conversations, list_events
from app.agent.runtime import resume_chat, start_chat


router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentRunResult)
async def chat(request: ChatRequest) -> AgentRunResult:
    try:
        return await start_chat(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/resume", response_model=AgentRunResult)
async def resume(request: ResumeRequest) -> AgentRunResult:
    try:
        return await resume_chat(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/conversations", response_model=list[ConversationResponse])
async def conversations() -> list[ConversationResponse]:
    rows = await list_conversations()
    return [
        ConversationResponse(
            id=row.id,
            title=row.title,
            status=row.status,
            langgraph_thread_id=row.langgraph_thread_id,
            last_event_seq=row.last_event_seq,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/conversations/{conversation_id}/events", response_model=EventHistoryResponse)
async def conversation_events(
    conversation_id: str,
    after_seq: int = 0,
    limit: int = 100,
) -> EventHistoryResponse:
    page_size = max(1, min(limit, 200))
    events = await list_events(conversation_id, after_seq=after_seq, limit=page_size + 1)
    return EventHistoryResponse(
        conversation_id=conversation_id,
        events=events[:page_size],
        has_more=len(events) > page_size,
    )

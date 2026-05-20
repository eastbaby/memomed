from collections.abc import AsyncIterator
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.api.schemas import (
    AgentRunResult,
    ChatRequest,
    ConversationResponse,
    EventHistoryResponse,
    ResumeRequest,
)
from app.agent.events.service import apply_conversation_seq_offset, get_last_event_seq, list_conversations, list_events
from app.agent.runtime import resume_chat, start_chat, stream_resume_chat, stream_start_chat


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


@router.post("/conversations/{conversation_id}/runs/stream")
async def chat_stream(conversation_id: str, request: ChatRequest) -> StreamingResponse:
    async def generate() -> AsyncIterator[str]:
        try:
            seq_offset = await get_last_event_seq(conversation_id)
            async for packet in stream_start_chat(ChatRequest(thread_id=conversation_id, message=request.message)):
                if packet.event:
                    event = packet.event.model_copy(deep=True)
                    event.seq = seq_offset + event.seq
                    yield _sse_event("agent_event", event.model_dump(mode="json"))
                if packet.result:
                    stream_result = apply_conversation_seq_offset(packet.result, seq_offset=seq_offset)
                    yield _sse_event("run_result", stream_result.model_dump(mode="json"))
                    yield _sse_event("done", {"thread_id": stream_result.thread_id, "status": stream_result.status})
        except Exception as exc:
            yield _sse_event("error", {"message": str(exc)})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_stream_headers())


@router.post("/conversations/{conversation_id}/runs/resume/stream")
async def resume_stream(conversation_id: str, request: ResumeRequest) -> StreamingResponse:
    async def generate() -> AsyncIterator[str]:
        try:
            seq_offset = await get_last_event_seq(conversation_id)
            async for packet in stream_resume_chat(ResumeRequest(thread_id=conversation_id, decision=request.decision)):
                if packet.event:
                    event = packet.event.model_copy(deep=True)
                    event.seq = seq_offset + event.seq
                    yield _sse_event("agent_event", event.model_dump(mode="json"))
                if packet.result:
                    stream_result = apply_conversation_seq_offset(packet.result, seq_offset=seq_offset)
                    yield _sse_event("run_result", stream_result.model_dump(mode="json"))
                    yield _sse_event("done", {"thread_id": stream_result.thread_id, "status": stream_result.status})
        except Exception as exc:
            yield _sse_event("error", {"message": str(exc)})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_stream_headers())


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


def _sse_event(event_name: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {data}\n\n"


def _stream_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

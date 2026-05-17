from typing import Any, Literal
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent.hitl.schemas import InteractionRequest


class ChatRequest(BaseModel):
    thread_id: str = Field(default_factory=lambda: f"thread-{uuid4().hex}")
    message: str


class ResumeRequest(BaseModel):
    thread_id: str
    decision: dict[str, Any]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AgentEvent(BaseModel):
    id: str
    conversation_id: str
    turn_id: str | None = None
    run_id: str | None = None
    work_item_id: str | None = None
    work_item_type: str | None = None
    seq: int
    event_type: str
    role: Literal["user", "assistant", "tool", "system"] | None = None
    visibility: Literal["visible", "collapsed", "debug", "hidden"] = "visible"
    status: Literal["pending", "streaming", "completed", "failed"] = "completed"
    parent_event_id: str | None = None
    dedupe_key: str | None = None
    title: str | None = None
    content: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(BaseModel):
    thread_id: str
    status: Literal["completed", "interrupted", "error"]
    events: list[AgentEvent] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list)
    process_events: list[dict[str, Any]] = Field(default_factory=list)
    interrupt: InteractionRequest | None = None
    error: str | None = None


class ConversationResponse(BaseModel):
    id: str
    title: str | None = None
    status: str
    langgraph_thread_id: str
    last_event_seq: int
    created_at: datetime
    updated_at: datetime


class EventHistoryResponse(BaseModel):
    conversation_id: str
    events: list[AgentEvent]
    has_more: bool = False

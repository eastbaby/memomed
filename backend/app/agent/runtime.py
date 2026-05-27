from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import perf_counter, time
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from app.agent.api.schemas import AgentEvent, AgentRunResult, ChatMessage, ChatRequest, ResumeRequest
from app.agent.events.emitter import AgentEventEmitter, AgentEventStreamBuffer, stable_token
from app.agent.events.service import persist_run_result
from app.agent.graph import graph


DISPLAY_DELTA_DELAY_SECONDS = 0.012
DISPLAY_DELTA_CHARS = 3


@dataclass(frozen=True)
class AgentStreamPacket:
    event: AgentEvent | None = None
    result: AgentRunResult | None = None


async def start_chat(request: ChatRequest) -> AgentRunResult:
    started_at = perf_counter()
    turn_started_at = time()
    result = await graph.ainvoke(
        _graph_input_for_user_message(request.message, turn_started_at),
        _config(request.thread_id, "memomed_chat_start"),
    )
    run_result = _to_run_result(
        request.thread_id,
        result,
        user_message=request.message,
        run_elapsed_seconds=_elapsed_seconds_since(started_at),
    )
    return await persist_run_result(run_result, trigger_type="user_message")


async def resume_chat(request: ResumeRequest) -> AgentRunResult:
    started_at = perf_counter()
    result = await graph.ainvoke(
        Command(resume=request.decision),
        _config(request.thread_id, "memomed_chat_resume"),
    )
    run_result = _to_run_result(
        request.thread_id,
        result,
        resume_decision=request.decision,
        run_elapsed_seconds=_elapsed_seconds_since(started_at),
    )
    return await persist_run_result(run_result, trigger_type="resume_interrupt")


async def stream_start_chat(request: ChatRequest) -> AsyncIterator[AgentStreamPacket]:
    turn_started_at = time()
    async for packet in _stream_graph_run(
        _graph_input_for_user_message(request.message, turn_started_at),
        request.thread_id,
        run_name="memomed_chat_start_stream",
        trigger_type="user_message",
        user_message=request.message,
    ):
        yield packet


async def stream_resume_chat(request: ResumeRequest) -> AsyncIterator[AgentStreamPacket]:
    async for packet in _stream_graph_run(
        Command(resume=request.decision),
        request.thread_id,
        run_name="memomed_chat_resume_stream",
        trigger_type="resume_interrupt",
        resume_decision=request.decision,
    ):
        yield packet


async def _stream_graph_run(
    graph_input: dict[str, Any] | Command,
    thread_id: str,
    *,
    run_name: str,
    trigger_type: str,
    user_message: str | None = None,
    resume_decision: dict[str, Any] | None = None,
) -> AsyncIterator[AgentStreamPacket]:
    started_at = perf_counter()
    run_id = f"run_{uuid4().hex}"
    emitter = AgentEventEmitter(thread_id, run_id)
    accumulated: dict[str, Any] = {}
    yielded_event_ids: set[str] = set()
    assistant_delta_content = ""
    assistant_delta_index = 0
    assistant_message_id = stable_token("msg", thread_id, run_id, "assistant")
    latest_ordinal = 0
    latest_delta_ordinal = 0
    streamed_events = AgentEventStreamBuffer()

    if user_message:
        for event in emitter.user_message_events(user_message):
            yielded_event_ids.add(event.id)
            latest_ordinal = max(latest_ordinal, event.ordinal)
            yield AgentStreamPacket(event=event)
        latest_ordinal = max(latest_ordinal, 2)
        for event in emitter.initial_process_events(latest_ordinal):
            yielded_event_ids.add(event.id)
            latest_ordinal = max(latest_ordinal, event.ordinal)
            streamed_events.append(event)
            yield AgentStreamPacket(event=event)
    else:
        latest_ordinal = 0
    latest_delta_ordinal = latest_ordinal

    async for chunk in graph.astream(
        graph_input,
        _config(thread_id, run_name),
        stream_mode=["updates", "messages", "custom"],
        version="v2",
    ):
        mode, data = _stream_chunk_mode_and_data(chunk)
        if mode == "custom":
            for event in emitter.custom_stream_events(data, latest_ordinal):
                yielded_event_ids.add(event.id)
                latest_ordinal = max(latest_ordinal, event.ordinal)
                latest_delta_ordinal = max(latest_delta_ordinal, latest_ordinal)
                streamed_events.append(event)
                yield AgentStreamPacket(event=event)
            continue
        if mode == "messages":
            delta = _message_chunk_text(data)
            if not delta or not delta.strip():
                continue
            async for event in emitter.assistant_delta_events_from_chunks(
                [delta],
                latest_ordinal=latest_delta_ordinal,
                assistant_delta_content=assistant_delta_content,
                assistant_delta_index=assistant_delta_index,
                message_id=assistant_message_id,
                display_delta_chars=DISPLAY_DELTA_CHARS,
                display_delta_delay_seconds=DISPLAY_DELTA_DELAY_SECONDS,
            ):
                assistant_delta_content += event.content or ""
                assistant_delta_index = int(event.payload["delta_index"])
                latest_delta_ordinal = event.ordinal
                yielded_event_ids.add(event.id)
                yield AgentStreamPacket(event=event)
            continue
        if mode != "updates":
            continue
        chunk = data
        _merge_stream_update(accumulated, chunk)
        if _call_model_finished_with_tool_call(chunk) and assistant_delta_content:
            latest_delta_ordinal += 1
            cancel_event = emitter.assistant_delta_cancelled_event(
                latest_delta_ordinal,
                message_id=assistant_message_id,
            )
            yielded_event_ids.add(cancel_event.id)
            yield AgentStreamPacket(event=cancel_event)
            assistant_delta_content = ""
            assistant_delta_index = 0
        partial_state = _partial_stream_state(accumulated, chunk)
        buffered_event_types_by_id = {event.id: event.event_type for event in streamed_events.events()}
        partial_result = _to_run_result(
            thread_id,
            partial_state,
            user_message=None,
            resume_decision=resume_decision,
            run_id=run_id,
            emitted_events=streamed_events.events(),
            event_ordinal_offset=2 if user_message else 1,
        )
        for event in partial_result.events:
            if event.event_type == "message.assistant.completed":
                continue
            if buffered_event_types_by_id.get(event.id) == event.event_type:
                continue
            event = emitter.event_with_stream_ordinal(event, latest_ordinal)
            if event.id in yielded_event_ids:
                continue
            yielded_event_ids.add(event.id)
            latest_ordinal = event.ordinal
            latest_delta_ordinal = max(latest_delta_ordinal, latest_ordinal)
            streamed_events.append(event)
            yield AgentStreamPacket(event=event)

    final_result = _to_run_result(
        thread_id,
        accumulated,
        user_message=user_message,
        resume_decision=resume_decision,
        run_id=run_id,
        emitted_events=streamed_events.events(),
        run_elapsed_seconds=_elapsed_seconds_since(started_at),
    )
    persisted_result = await persist_run_result(final_result, trigger_type=trigger_type)  # type: ignore[arg-type]
    yield AgentStreamPacket(result=persisted_result)


def _stream_chunk_mode_and_data(chunk: Any) -> tuple[str, Any]:
    if isinstance(chunk, dict) and isinstance(chunk.get("type"), str) and "data" in chunk:
        return chunk["type"], chunk["data"]
    if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], str):
        return chunk[0], chunk[1]
    return "updates", chunk


def _message_chunk_text(data: Any) -> str:
    if not (isinstance(data, tuple) and len(data) == 2):
        return ""
    message, metadata = data
    if isinstance(metadata, dict) and metadata.get("langgraph_node") != "call_model":
        return ""
    if getattr(message, "tool_calls", None) or getattr(message, "tool_call_chunks", None):
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_part_text(part) for part in content)
    return ""


def _call_model_finished_with_tool_call(chunk: Any) -> bool:
    message = _call_model_update_message(chunk)
    return message is not None and bool(getattr(message, "tool_calls", None))


def _call_model_update_message(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    update = chunk.get("call_model")
    if not isinstance(update, dict):
        return None
    messages = update.get("messages")
    if not messages:
        return None
    return messages[-1]


def _content_part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict) and part.get("type") == "text":
        text = part.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _merge_stream_update(accumulated: dict[str, Any], chunk: Any) -> None:
    if not isinstance(chunk, dict):
        return
    if "__interrupt__" in chunk:
        accumulated["__interrupt__"] = chunk["__interrupt__"]
        return
    for update in chunk.values():
        if not isinstance(update, dict):
            continue
        for key, value in update.items():
            if key == "messages":
                accumulated.setdefault(key, [])
                accumulated[key].extend(value or [])
            else:
                accumulated[key] = value


def _partial_stream_state(accumulated: dict[str, Any], chunk: Any) -> dict[str, Any]:
    partial = dict(accumulated)
    if not (isinstance(chunk, dict) and "final_answer" in chunk):
        partial.pop("response", None)
    return partial


def _config(thread_id: str, run_name: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": run_name,
        "tags": ["memomed", "agent-loop", "backend"],
        "metadata": {
            "thread_id": thread_id,
            "app": "memomed",
            "surface": "local_frontend",
        },
    }


def _graph_input_for_user_message(message: str, turn_started_at: float) -> dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": message}],
        "metadata": {
            "turn_started_at": turn_started_at,
            "turn_key": stable_token("turn", message, f"{turn_started_at:.6f}"),
        },
    }


def _to_run_result(
    thread_id: str,
    result: dict[str, Any],
    *,
    user_message: str | None = None,
    resume_decision: dict[str, Any] | None = None,
    run_id: str | None = None,
    emitted_events: list[AgentEvent] | None = None,
    event_ordinal_offset: int = 0,
    run_elapsed_seconds: int | None = None,
) -> AgentRunResult:
    run_id = run_id or f"run_{uuid4().hex}"
    emitter = AgentEventEmitter(thread_id, run_id)
    interrupts = result.get("__interrupt__")
    if interrupts:
        interrupt_value = interrupts[0].value
        return AgentRunResult(
            thread_id=thread_id,
            status="interrupted",
            events=emitter.run_result_events(
                user_message=user_message,
                emitted_events=emitted_events,
                interrupt=interrupt_value,
                resume_decision=resume_decision,
                ordinal_offset=event_ordinal_offset,
                run_elapsed_seconds=run_elapsed_seconds,
            ),
            interrupt=interrupt_value,
        )

    response = result.get("response")
    messages = [ChatMessage(role="assistant", content=response)] if response else []
    metadata_status = result.get("metadata", {}).get("status")
    status = "error" if metadata_status in {"llm_empty_response", "final_answer_missing"} else "completed"
    error = _agent_error_message(metadata_status) if status == "error" else None
    return AgentRunResult(
        thread_id=thread_id,
        status=status,
        events=emitter.run_result_events(
            user_message=user_message,
            emitted_events=emitted_events,
            assistant_response=response,
            resume_decision=resume_decision,
            ordinal_offset=event_ordinal_offset,
            run_elapsed_seconds=run_elapsed_seconds,
        ),
        messages=messages,
        interrupt=None,
        error=error,
    )


def _agent_error_message(metadata_status: str | None) -> str:
    if metadata_status == "final_answer_missing":
        return "Agent 工具流程结束后缺少最终回复文本。"
    return "LLM 没有返回最终回复文本。"


def _elapsed_seconds_since(started_at: float) -> int:
    return max(0, int(perf_counter() - started_at))

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from hashlib import sha1
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from app.agent.api.schemas import AgentEvent, AgentRunResult, ChatMessage, ChatRequest, ResumeRequest
from app.agent.events.service import persist_run_result
from app.agent.graph import graph


DISPLAY_DELTA_DELAY_SECONDS = 0.012
DISPLAY_DELTA_CHARS = 3


@dataclass(frozen=True)
class AgentStreamPacket:
    event: AgentEvent | None = None
    result: AgentRunResult | None = None


async def start_chat(request: ChatRequest) -> AgentRunResult:
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": request.message}], "metadata": {}},
        _config(request.thread_id, "memomed_chat_start"),
    )
    run_result = _to_run_result(request.thread_id, result, user_message=request.message)
    await persist_run_result(run_result, trigger_type="user_message")
    return run_result


async def resume_chat(request: ResumeRequest) -> AgentRunResult:
    result = await graph.ainvoke(
        Command(resume=request.decision),
        _config(request.thread_id, "memomed_chat_resume"),
    )
    run_result = _to_run_result(request.thread_id, result, resume_decision=request.decision)
    await persist_run_result(run_result, trigger_type="resume_interrupt")
    return run_result


async def stream_start_chat(request: ChatRequest) -> AsyncIterator[AgentStreamPacket]:
    async for packet in _stream_graph_run(
        {"messages": [{"role": "user", "content": request.message}], "metadata": {}},
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
    run_id = f"run_{uuid4().hex}"
    accumulated: dict[str, Any] = {}
    yielded_event_ids: set[str] = set()
    assistant_delta_content = ""
    assistant_delta_index = 0
    assistant_message_id = _stable_token("msg", thread_id, run_id, "assistant")
    latest_seq = 0
    buffered_delta_chunks: list[str] = []
    streamed_process_events: list[dict[str, Any]] = []

    if user_message:
        for event in _agent_events(thread_id, run_id, user_message=user_message):
            yielded_event_ids.add(event.id)
            latest_seq = max(latest_seq, event.seq)
            yield AgentStreamPacket(event=event)

    async for chunk in graph.astream(
        graph_input,
        _config(thread_id, run_name),
        stream_mode=["updates", "messages", "custom"],
        version="v2",
    ):
        mode, data = _stream_chunk_mode_and_data(chunk)
        if mode == "custom":
            for event in _custom_stream_events(thread_id, run_id, data, yielded_event_ids, latest_seq):
                yielded_event_ids.add(event.id)
                latest_seq = max(latest_seq, event.seq)
                if event.event_type == "process.step":
                    streamed_process_events.append(
                        {
                            "text": event.content or "",
                            "step_type": event.payload.get("step_type"),
                        }
                    )
                yield AgentStreamPacket(event=event)
            continue
        if mode == "messages":
            delta = _message_chunk_text(data)
            if not delta or not delta.strip():
                continue
            buffered_delta_chunks.append(delta)
            continue
        if mode != "updates":
            continue
        chunk = data
        _merge_stream_update(accumulated, chunk)
        if _call_model_finished_without_tool_call(chunk) and not assistant_delta_content and buffered_delta_chunks:
            async for event in _assistant_delta_events_from_chunks(
                thread_id,
                run_id,
                buffered_delta_chunks,
                latest_seq=latest_seq,
                assistant_delta_content=assistant_delta_content,
                assistant_delta_index=assistant_delta_index,
                message_id=assistant_message_id,
            ):
                assistant_delta_content += event.content or ""
                assistant_delta_index = int(event.payload["delta_index"])
                latest_seq = event.seq
                yielded_event_ids.add(event.id)
                yield AgentStreamPacket(event=event)
        if _call_model_finished_with_tool_call(chunk):
            buffered_delta_chunks = []
        partial_state = _partial_stream_state(_state_with_streamed_process_events(accumulated, streamed_process_events), chunk)
        partial_result = _to_run_result(
            thread_id,
            partial_state,
            user_message=None,
            resume_decision=resume_decision,
            run_id=run_id,
            event_seq_offset=1 if user_message else 0,
        )
        for event in partial_result.events:
            if event.id in yielded_event_ids:
                continue
            event = _event_with_stream_seq(event, latest_seq)
            yielded_event_ids.add(event.id)
            latest_seq = event.seq
            yield AgentStreamPacket(event=event)

    final_result = _to_run_result(
        thread_id,
        _state_with_streamed_process_events(accumulated, streamed_process_events),
        user_message=user_message,
        resume_decision=resume_decision,
        run_id=run_id,
    )
    await persist_run_result(final_result, trigger_type=trigger_type)  # type: ignore[arg-type]
    yield AgentStreamPacket(result=final_result)


def _stream_chunk_mode_and_data(chunk: Any) -> tuple[str, Any]:
    if isinstance(chunk, dict) and isinstance(chunk.get("type"), str) and "data" in chunk:
        return chunk["type"], chunk["data"]
    if isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], str):
        return chunk[0], chunk[1]
    return "updates", chunk


def _custom_stream_events(
    thread_id: str,
    run_id: str,
    data: Any,
    yielded_event_ids: set[str],
    latest_seq: int,
) -> list[AgentEvent]:
    if not isinstance(data, dict) or data.get("type") != "process_step":
        return []

    step_type = str(data.get("step_type") or "")
    text = str(data.get("text") or "")
    if not text or not step_type:
        return []

    work_item_type = str(data.get("work_item_type") or "agent")
    work_item_id = _stable_token("wi", thread_id, run_id, work_item_type)
    turn_id = _stable_token("turn", thread_id, run_id, work_item_type)
    process_group_id = _stable_event_id(thread_id, "process.group", work_item_id)
    events: list[AgentEvent] = []
    seq = latest_seq

    if process_group_id not in yielded_event_ids:
        seq += 1
        events.append(
            AgentEvent(
                id=process_group_id,
                conversation_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                seq=seq,
                event_type="process.group.started",
                role="assistant",
                visibility="collapsed",
                status="streaming",
                title=str(data.get("group_title") or _work_item_title(work_item_type)),
                content=text,
                payload={"default_expanded": False, "source": "langgraph_custom_stream"},
            )
        )

    failed = step_type == "tool.error"
    event_id = _stable_event_id(thread_id, "process.step", work_item_id, step_type, text)
    if event_id in yielded_event_ids:
        return events
    seq += 1
    events.append(
        AgentEvent(
            id=event_id,
            conversation_id=thread_id,
            turn_id=turn_id,
            run_id=run_id,
            work_item_id=work_item_id,
            work_item_type=work_item_type,
            seq=seq,
            event_type="process.step",
            role="tool" if step_type in {"tool.observation", "tool.error"} else "assistant",
            visibility="collapsed",
            status="failed" if failed else "completed",
            parent_event_id=process_group_id,
            dedupe_key=f"process:{step_type}:{_short_hash(text)}",
            title=str(data.get("title") or _process_event_title(step_type)),
            content=text,
            payload={
                "source": "langgraph_custom_stream",
                **(data.get("payload") if isinstance(data.get("payload"), dict) else {}),
                "step_type": step_type,
            },
        )
    )
    return events


def _state_with_streamed_process_events(
    state: dict[str, Any],
    streamed_process_events: list[dict[str, Any]],
) -> dict[str, Any]:
    if not streamed_process_events:
        return state
    merged = dict(state)
    merged["process_events"] = [*streamed_process_events, *list(state.get("process_events", []))]
    return merged


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


def _call_model_finished_without_tool_call(chunk: Any) -> bool:
    message = _call_model_update_message(chunk)
    return message is not None and not bool(getattr(message, "tool_calls", None))


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


def _display_delta_pieces(delta: str) -> list[str]:
    if len(delta) <= DISPLAY_DELTA_CHARS:
        return [delta]
    return [delta[index : index + DISPLAY_DELTA_CHARS] for index in range(0, len(delta), DISPLAY_DELTA_CHARS)]


async def _assistant_delta_events_from_chunks(
    thread_id: str,
    run_id: str,
    chunks: list[str],
    *,
    latest_seq: int,
    assistant_delta_content: str,
    assistant_delta_index: int,
    message_id: str,
) -> AsyncIterator[AgentEvent]:
    content = assistant_delta_content
    delta_index = assistant_delta_index
    seq = latest_seq
    for chunk in chunks:
        for piece in _display_delta_pieces(chunk):
            content += piece
            delta_index += 1
            seq += 1
            event = _assistant_delta_event(
                thread_id,
                run_id,
                piece,
                seq,
                message_id=message_id,
                delta_index=delta_index,
                offset=len(content),
            )
            yield event
            await asyncio.sleep(DISPLAY_DELTA_DELAY_SECONDS)


def _content_part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict) and part.get("type") == "text":
        text = part.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _assistant_delta_event(
    thread_id: str,
    run_id: str,
    content: str,
    seq: int,
    *,
    message_id: str,
    delta_index: int,
    offset: int,
) -> AgentEvent:
    return AgentEvent(
        id=_stable_event_id(thread_id, "message.assistant.delta", message_id, delta_index),
        conversation_id=thread_id,
        turn_id=_stable_token("turn", thread_id, "agent"),
        run_id=run_id,
        seq=seq,
        event_type="message.assistant.delta",
        role="assistant",
        visibility="visible",
        status="streaming",
        content=content,
        payload={
            "streaming": True,
            "message_id": message_id,
            "delta": True,
            "delta_index": delta_index,
            "offset": offset,
        },
    )


def _event_with_stream_seq(event: AgentEvent, latest_seq: int) -> AgentEvent:
    if event.seq > latest_seq:
        return event
    return event.model_copy(update={"seq": latest_seq + 1})


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
            if key in {"messages", "process_events"}:
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


def _to_run_result(
    thread_id: str,
    result: dict[str, Any],
    *,
    user_message: str | None = None,
    resume_decision: dict[str, Any] | None = None,
    run_id: str | None = None,
    event_seq_offset: int = 0,
) -> AgentRunResult:
    run_id = run_id or f"run_{uuid4().hex}"
    interrupts = result.get("__interrupt__")
    if interrupts:
        interrupt_value = interrupts[0].value
        process_events = _events_for_interrupt(result, interrupt_value)
        return AgentRunResult(
            thread_id=thread_id,
            status="interrupted",
            events=_agent_events(
                thread_id,
                run_id,
                user_message=user_message,
                process_events=process_events,
                interrupt=interrupt_value,
                resume_decision=resume_decision,
                seq_offset=event_seq_offset,
            ),
            process_events=process_events,
            interrupt=interrupt_value,
        )

    process_events = _dedupe_process_events(result.get("process_events", []))
    response = result.get("response")
    messages = [ChatMessage(role="assistant", content=response)] if response else []
    metadata_status = result.get("metadata", {}).get("status")
    status = "error" if metadata_status in {"llm_empty_response", "final_answer_missing"} else "completed"
    error = _agent_error_message(metadata_status) if status == "error" else None
    return AgentRunResult(
        thread_id=thread_id,
        status=status,
        events=_agent_events(
            thread_id,
            run_id,
            user_message=user_message,
            process_events=process_events,
            assistant_response=response,
            resume_decision=resume_decision,
            seq_offset=event_seq_offset,
        ),
        messages=messages,
        process_events=process_events,
        interrupt=None,
        error=error,
    )


def _events_for_interrupt(result: dict[str, Any], interaction: dict[str, Any]) -> list[dict[str, Any]]:
    events = _dedupe_process_events(result.get("process_events", []))
    current = _process_event_for_interrupt(interaction)
    if any(
        event.get("step_type") == current.get("step_type") and event.get("text") == current.get("text")
        for event in events
    ):
        return events
    return [*events, current]


def _agent_error_message(metadata_status: str | None) -> str:
    if metadata_status == "final_answer_missing":
        return "Agent 工具流程结束后缺少最终回复文本。"
    return "LLM 没有返回最终回复文本。"


def _process_event_for_interrupt(interaction: dict[str, Any]) -> dict[str, Any]:
    text = interaction.get("description") or interaction.get("title") or "需要你确认后继续。"
    return {"step_type": "runtime.note", "text": text}


def _dedupe_process_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        step_type = str(event.get("step_type") or "")
        if not step_type:
            continue
        text = str(event.get("text", ""))
        key = (step_type, text)
        if key in seen:
            continue
        seen.add(key)
        unique_events.append({"text": text, "step_type": step_type})
    return unique_events


def _agent_events(
    thread_id: str,
    run_id: str,
    *,
    user_message: str | None = None,
    process_events: list[dict[str, Any]] | None = None,
    assistant_response: str | None = None,
    interrupt: dict[str, Any] | None = None,
    resume_decision: dict[str, Any] | None = None,
    seq_offset: int = 0,
) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    work_item_type = _work_item_type(process_events or [], interrupt)
    work_item_id = _stable_token("wi", thread_id, run_id, work_item_type) if work_item_type else None
    turn_id = _stable_token("turn", thread_id, run_id, user_message or work_item_type or "agent")

    def next_seq() -> int:
        return seq_offset + len(events) + 1

    if user_message:
        events.append(
            AgentEvent(
                id=_stable_event_id(thread_id, "message.user", user_message),
                conversation_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                seq=next_seq(),
                event_type="message.user",
                role="user",
                content=user_message,
            )
        )

    process_events = process_events or []
    process_group_id: str | None = None
    if process_events:
        latest_text = process_events[-1].get("text") or "Agent 正在处理。"
        process_group_id = _stable_event_id(thread_id, "process.group", work_item_id or latest_text)
        events.append(
            AgentEvent(
                id=process_group_id,
                conversation_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                seq=next_seq(),
                event_type="process.group.started",
                role="assistant",
                visibility="collapsed",
                status="streaming" if interrupt else "completed",
                title=_work_item_title(work_item_type),
                content=latest_text,
                payload={"default_expanded": False},
            )
        )

    for process_event in process_events:
        step_type = str(process_event.get("step_type") or "")
        if not step_type:
            continue
        text = process_event.get("text", "")
        failed = step_type == "tool.error"
        events.append(
            AgentEvent(
                id=_stable_event_id(thread_id, "process.step", work_item_id, step_type, text),
                conversation_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                seq=next_seq(),
                event_type="process.step",
                role="tool" if step_type in {"tool.observation", "tool.error"} else "assistant",
                visibility="collapsed",
                status="failed" if failed else "completed",
                parent_event_id=process_group_id,
                dedupe_key=f"process:{step_type}:{_short_hash(text)}",
                title=_process_event_title(step_type),
                content=text,
                payload={"step_type": step_type},
            )
        )

    if resume_decision:
        events.append(
            AgentEvent(
                id=_stable_event_id(thread_id, "interrupt.resumed", resume_decision),
                conversation_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                seq=next_seq(),
                event_type="interrupt.resumed",
                role="assistant",
                visibility="collapsed",
                status="completed",
                parent_event_id=process_group_id,
                dedupe_key=f"interrupt.resumed:{_short_hash(str(resume_decision))}",
                title="用户已确认",
                content="用户已完成确认，Agent 继续执行。",
                payload={"decision": resume_decision},
            )
        )

    if interrupt:
        text = interrupt.get("description") or interrupt.get("title") or "需要你确认后继续。"
        pending_action = interrupt.get("pending_action") or {}
        events.append(
            AgentEvent(
                id=_stable_event_id(thread_id, "interrupt.requested", pending_action.get("id"), text),
                conversation_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                seq=next_seq(),
                event_type="interrupt.requested",
                role="assistant",
                visibility="visible",
                status="pending",
                title=interrupt.get("title") or "需要确认",
                content=text,
                payload={"interaction": interrupt},
            )
        )

    if assistant_response:
        events.append(
            AgentEvent(
                id=_stable_event_id(thread_id, "message.assistant.completed", assistant_response),
                conversation_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                seq=next_seq(),
                event_type="message.assistant.completed",
                role="assistant",
                content=assistant_response,
            )
        )

    return events


def _process_event_title(step_type: str) -> str:
    if step_type == "tool.error":
        return "执行失败"
    if step_type == "tool.observation":
        return "工具结果"
    if step_type == "tool.started":
        return "工具调用"
    return "思考过程"


def _work_item_type(process_events: list[dict[str, Any]], interrupt: dict[str, Any] | None) -> str | None:
    if process_events or interrupt:
        return "subject_resolution"
    return None


def _work_item_title(work_item_type: str | None) -> str:
    if work_item_type == "subject_resolution":
        return "确认健康档案对象"
    return "Agent 过程"


def _stable_event_id(thread_id: str, event_type: str, *parts: Any) -> str:
    raw = "|".join([thread_id, event_type, *[str(part or "") for part in parts]])
    return f"evt_{_short_hash(raw)}"


def _stable_token(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}_{_short_hash(raw)}"


def _short_hash(value: str) -> str:
    return sha1(value.encode("utf-8")).hexdigest()[:16]

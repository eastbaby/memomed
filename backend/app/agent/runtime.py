from hashlib import sha1
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from app.agent.api.schemas import AgentEvent, AgentRunResult, ChatMessage, ChatRequest, ResumeRequest
from app.agent.events.service import persist_run_result
from app.agent.graph import graph


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
    run_result = _to_run_result(request.thread_id, result)
    await persist_run_result(run_result, trigger_type="resume_interrupt")
    return run_result


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
) -> AgentRunResult:
    run_id = f"run_{uuid4().hex}"
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
            ),
            process_events=process_events,
            interrupt=interrupt_value,
        )

    response = result.get("response")
    messages = [ChatMessage(role="assistant", content=response)] if response else []
    process_events = _dedupe_process_events(result.get("process_events", []))
    return AgentRunResult(
        thread_id=thread_id,
        status="completed",
        events=_agent_events(
            thread_id,
            run_id,
            user_message=user_message,
            process_events=process_events,
            assistant_response=response,
        ),
        messages=messages,
        process_events=process_events,
        interrupt=None,
    )


def _events_for_interrupt(result: dict[str, Any], interaction: dict[str, Any]) -> list[dict[str, Any]]:
    events = _dedupe_process_events(result.get("process_events", []))
    current = _process_event_for_interrupt(interaction)
    if any(event.get("type") == current.get("type") and event.get("text") == current.get("text") for event in events):
        return events
    return [*events, current]


def _process_event_for_interrupt(interaction: dict[str, Any]) -> dict[str, Any]:
    text = interaction.get("description") or interaction.get("title") or "需要你确认后继续。"
    return {"type": "thinking", "text": text}


def _dedupe_process_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        event_type = str(event.get("type", "thinking"))
        text = str(event.get("text", ""))
        key = (event_type, text)
        if key in seen:
            continue
        seen.add(key)
        unique_events.append({"type": event_type, "text": text})
    return unique_events


def _agent_events(
    thread_id: str,
    run_id: str,
    *,
    user_message: str | None = None,
    process_events: list[dict[str, Any]] | None = None,
    assistant_response: str | None = None,
    interrupt: dict[str, Any] | None = None,
) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    work_item_type = _work_item_type(process_events or [], interrupt)
    work_item_id = _stable_token("wi", thread_id, work_item_type) if work_item_type else None
    turn_id = _stable_token("turn", thread_id, user_message or work_item_type or "agent")

    def next_seq() -> int:
        return len(events) + 1

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
        process_group_id = _stable_event_id(thread_id, "process.group", latest_text)
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
        legacy_type = process_event.get("type", "thinking")
        text = process_event.get("text", "")
        failed = legacy_type == "error"
        events.append(
            AgentEvent(
                id=_stable_event_id(thread_id, "process.step", legacy_type, text),
                conversation_id=thread_id,
                turn_id=turn_id,
                run_id=run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                seq=next_seq(),
                event_type="process.step",
                role="tool" if legacy_type in {"tool_result", "error"} else "assistant",
                visibility="collapsed",
                status="failed" if failed else "completed",
                parent_event_id=process_group_id,
                dedupe_key=f"process:{legacy_type}:{_short_hash(text)}",
                title=_process_event_title(legacy_type),
                content=text,
                payload={"legacy_type": legacy_type},
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


def _process_event_title(event_type: str) -> str:
    if event_type == "error":
        return "执行失败"
    if event_type == "tool_result":
        return "工具结果"
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

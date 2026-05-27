import asyncio
from collections.abc import AsyncIterator
from hashlib import sha1
from typing import Any

from app.agent.api.schemas import AgentEvent
from app.agent.tools.registry import capability_display_name


class AgentEventEmitter:
    def __init__(self, thread_id: str, run_id: str) -> None:
        self.thread_id = thread_id
        self.run_id = run_id
        self._stream_process_group_ids_by_work_item: dict[str, str] = {}

    def user_message_events(self, message: str) -> list[AgentEvent]:
        return self.run_result_events(user_message=message)

    def initial_process_events(self, latest_ordinal: int) -> list[AgentEvent]:
        work_item_type = "agent_progress"
        work_item_id = stable_token("wi", self.thread_id, self.run_id, work_item_type)
        turn_id = stable_token("turn", self.thread_id, self.run_id, work_item_type)
        group_ordinal = latest_ordinal + 1
        step_ordinal = latest_ordinal + 2
        process_group_id = event_id_for_ordinal(self.run_id, group_ordinal)
        text = "正在理解需求并选择合适的工具。"
        return [
            AgentEvent(
                id=process_group_id,
                conversation_id=self.thread_id,
                turn_id=turn_id,
                run_id=self.run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                ordinal=group_ordinal,
                seq=None,
                event_type="process.group.started",
                role="assistant",
                visibility="collapsed",
                status="streaming",
                title="Agent 过程",
                content=text,
                payload={"default_expanded": False, "source": "runtime_start"},
            ),
            AgentEvent(
                id=event_id_for_ordinal(self.run_id, step_ordinal),
                conversation_id=self.thread_id,
                turn_id=turn_id,
                run_id=self.run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                ordinal=step_ordinal,
                seq=None,
                event_type="process.step",
                role="assistant",
                visibility="collapsed",
                status="streaming",
                parent_event_id=process_group_id,
                title="处理进度",
                content=text,
                payload={"source": "runtime_start", "step_type": "agent.progress"},
            ),
        ]

    def custom_stream_events(
        self,
        data: Any,
        latest_ordinal: int,
    ) -> list[AgentEvent]:
        if not isinstance(data, dict) or data.get("type") != "process_step":
            return []

        step_type = str(data.get("step_type") or "")
        text = str(data.get("text") or "")
        if not text or not step_type:
            return []

        work_item_type = str(data.get("work_item_type") or "agent")
        work_item_id = stable_token("wi", self.thread_id, self.run_id, work_item_type)
        turn_id = stable_token("turn", self.thread_id, self.run_id, work_item_type)
        events: list[AgentEvent] = []
        ordinal = latest_ordinal

        process_group_id = self._stream_process_group_ids_by_work_item.get(work_item_id)
        if process_group_id is None:
            ordinal += 1
            process_group_id = event_id_for_ordinal(self.run_id, ordinal)
            self._stream_process_group_ids_by_work_item[work_item_id] = process_group_id
            events.append(
                AgentEvent(
                    id=process_group_id,
                    conversation_id=self.thread_id,
                    turn_id=turn_id,
                    run_id=self.run_id,
                    work_item_id=work_item_id,
                    work_item_type=work_item_type,
                    ordinal=ordinal,
                    seq=None,
                    event_type="process.group.started",
                    role="assistant",
                    visibility="collapsed",
                    status="streaming",
                    title=str(data.get("group_title") or work_item_title(work_item_type)),
                    content=text,
                    payload={"default_expanded": False, "source": "langgraph_custom_stream"},
                )
            )

        failed = step_type == "tool.error"
        ordinal += 1
        event_id = event_id_for_ordinal(self.run_id, ordinal)
        events.append(
            AgentEvent(
                id=event_id,
                conversation_id=self.thread_id,
                turn_id=turn_id,
                run_id=self.run_id,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                ordinal=ordinal,
                seq=None,
                event_type="process.step",
                role="tool" if step_type in {"tool.observation", "tool.error"} else "assistant",
                visibility="collapsed",
                status="failed" if failed else "completed",
                parent_event_id=process_group_id,
                title=str(data.get("title") or process_event_title(step_type)),
                content=text,
                payload={
                    "source": "langgraph_custom_stream",
                    **(data.get("payload") if isinstance(data.get("payload"), dict) else {}),
                    "step_type": step_type,
                },
            )
        )
        return events

    async def assistant_delta_events_from_chunks(
        self,
        chunks: list[str],
        *,
        latest_ordinal: int,
        assistant_delta_content: str,
        assistant_delta_index: int,
        message_id: str,
        display_delta_chars: int,
        display_delta_delay_seconds: float,
    ) -> AsyncIterator[AgentEvent]:
        content = assistant_delta_content
        delta_index = assistant_delta_index
        ordinal = latest_ordinal
        for chunk in chunks:
            for piece in display_delta_pieces(chunk, display_delta_chars):
                content += piece
                delta_index += 1
                ordinal += 1
                yield self.assistant_delta_event(
                    piece,
                    ordinal,
                    message_id=message_id,
                    delta_index=delta_index,
                    offset=len(content),
                )
                if display_delta_delay_seconds:
                    await asyncio.sleep(display_delta_delay_seconds)

    def assistant_delta_event(
        self,
        content: str,
        ordinal: int,
        *,
        message_id: str,
        delta_index: int,
        offset: int,
    ) -> AgentEvent:
        return AgentEvent(
            id=stable_event_id(self.thread_id, "message.assistant.delta", message_id, delta_index),
            conversation_id=self.thread_id,
            turn_id=stable_token("turn", self.thread_id, "agent"),
            run_id=self.run_id,
            ordinal=ordinal,
            seq=None,
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

    def assistant_delta_cancelled_event(self, ordinal: int, *, message_id: str) -> AgentEvent:
        return AgentEvent(
            id=stable_event_id(self.thread_id, "message.assistant.cancelled", message_id, ordinal),
            conversation_id=self.thread_id,
            turn_id=stable_token("turn", self.thread_id, "agent"),
            run_id=self.run_id,
            ordinal=ordinal,
            seq=None,
            event_type="message.assistant.cancelled",
            role="assistant",
            visibility="hidden",
            status="completed",
            payload={
                "message_id": message_id,
                "reason": "tool_call_started",
            },
        )

    def event_with_stream_ordinal(self, event: AgentEvent, latest_ordinal: int) -> AgentEvent:
        if event.ordinal > latest_ordinal:
            return event
        ordinal = latest_ordinal + 1
        return event.model_copy(
            update={"id": event_id_for_ordinal(self.run_id, ordinal), "ordinal": ordinal, "seq": None}
        )

    def run_result_events(
        self,
        *,
        user_message: str | None = None,
        emitted_events: list[AgentEvent] | None = None,
        assistant_response: str | None = None,
        interrupt: dict[str, Any] | None = None,
        resume_decision: dict[str, Any] | None = None,
        ordinal_offset: int = 0,
        run_elapsed_seconds: int | None = None,
    ) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        first_emitted_work_item_type = _first_work_item_type(emitted_events or [])
        work_item_id = _first_work_item_id(emitted_events or [])
        turn_id = stable_token("turn", self.thread_id, self.run_id, user_message or first_emitted_work_item_type or "agent")

        def next_ordinal() -> int:
            if not events:
                return ordinal_offset + 1
            return max(event.ordinal for event in events) + 1

        def next_event_id(ordinal: int) -> str:
            return event_id_for_ordinal(self.run_id, ordinal)

        if user_message:
            ordinal = next_ordinal()
            events.append(
                AgentEvent(
                    id=next_event_id(ordinal),
                    conversation_id=self.thread_id,
                    turn_id=turn_id,
                    run_id=self.run_id,
                    ordinal=ordinal,
                    seq=None,
                    event_type="message.user",
                    role="user",
                    content=user_message,
                )
            )

        if run_elapsed_seconds is not None:
            elapsed_seconds = max(0, int(run_elapsed_seconds))
            ordinal = next_ordinal()
            events.append(
                AgentEvent(
                    id=next_event_id(ordinal),
                    conversation_id=self.thread_id,
                    turn_id=turn_id,
                    run_id=self.run_id,
                    ordinal=ordinal,
                    seq=None,
                    event_type="run.elapsed",
                    role="assistant",
                    visibility="collapsed",
                    status="completed",
                    content=f"已处理 {format_elapsed_seconds(elapsed_seconds)}",
                    payload={"elapsed_seconds": elapsed_seconds},
                )
            )

        process_group_id: str | None = None
        emitted_event_types = {event.event_type for event in emitted_events or []}
        if emitted_events is not None:
            finalized_process_events = finalize_emitted_events(
                emitted_events,
                interrupt=interrupt,
            )
            for event in finalized_process_events:
                if process_group_id is None and event.event_type == "process.group.started":
                    process_group_id = event.id
                events.append(event)

        if resume_decision and "interrupt.resumed" not in emitted_event_types:
            ordinal = next_ordinal()
            events.append(
                AgentEvent(
                    id=next_event_id(ordinal),
                    conversation_id=self.thread_id,
                    turn_id=turn_id,
                    run_id=self.run_id,
                    work_item_id=work_item_id,
                    work_item_type=first_emitted_work_item_type,
                    ordinal=ordinal,
                    seq=None,
                    event_type="interrupt.resumed",
                    role="assistant",
                    visibility="collapsed",
                    status="completed",
                    parent_event_id=process_group_id,
                    dedupe_key=f"interrupt.resumed:{short_hash(str(resume_decision))}",
                    title="用户已确认",
                    content="用户已完成确认，Agent 继续执行。",
                    payload={"decision": resume_decision},
                )
            )

        if interrupt and "interrupt.requested" not in emitted_event_types:
            text = interrupt.get("description") or interrupt.get("title") or "需要你确认后继续。"
            ordinal = next_ordinal()
            events.append(
                AgentEvent(
                    id=next_event_id(ordinal),
                    conversation_id=self.thread_id,
                    turn_id=turn_id,
                    run_id=self.run_id,
                    work_item_id=work_item_id,
                    work_item_type=first_emitted_work_item_type,
                    ordinal=ordinal,
                    seq=None,
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
            ordinal = next_ordinal()
            events.append(
                AgentEvent(
                    id=next_event_id(ordinal),
                    conversation_id=self.thread_id,
                    turn_id=turn_id,
                    run_id=self.run_id,
                    ordinal=ordinal,
                    seq=None,
                    event_type="message.assistant.completed",
                    role="assistant",
                    content=assistant_response,
                )
            )

        return events

class AgentEventStreamBuffer:
    def __init__(self) -> None:
        self._events: list[AgentEvent] = []

    def append(self, event: AgentEvent) -> None:
        if event.event_type in {"process.group.started", "process.step", "interrupt.requested", "interrupt.resumed"}:
            self._events.append(event)

    def events(self) -> list[AgentEvent]:
        return list(self._events)

def finalize_emitted_events(
    emitted_events: list[AgentEvent],
    *,
    interrupt: dict[str, Any] | None,
) -> list[AgentEvent]:
    finalized_events: list[AgentEvent] = []
    for event in sorted(emitted_events, key=lambda item: item.ordinal):
        if event.event_type == "process.group.started":
            finalized_events.append(
                event.model_copy(
                    update={
                        "seq": None,
                        "status": "streaming" if interrupt else "completed",
                        "payload": {"default_expanded": event.payload.get("default_expanded", False)},
                    }
                )
            )
            continue
        if event.event_type in {"interrupt.requested", "interrupt.resumed"}:
            finalized_events.append(event.model_copy(update={"seq": None}))
            continue
        if event.event_type == "process.step":
            step_type = event.payload.get("step_type")
            failed = step_type == "tool.error"
            finalized_events.append(
                event.model_copy(
                    update={
                        "seq": None,
                        "status": "failed" if failed else "completed",
                    }
                )
            )
    return finalized_events


def display_delta_pieces(delta: str, display_delta_chars: int) -> list[str]:
    if len(delta) <= display_delta_chars:
        return [delta]
    return [delta[index : index + display_delta_chars] for index in range(0, len(delta), display_delta_chars)]


def process_event_title(step_type: str) -> str:
    if step_type == "agent.progress":
        return "处理进度"
    if step_type == "tool.error":
        return "执行失败"
    if step_type == "tool.observation":
        return "工具结果"
    if step_type == "tool.started":
        return "工具调用"
    return "思考过程"


def _first_work_item_type(events: list[AgentEvent]) -> str | None:
    for event in events:
        if event.work_item_type:
            return event.work_item_type
    return None


def _first_work_item_id(events: list[AgentEvent]) -> str | None:
    for event in events:
        if event.work_item_id:
            return event.work_item_id
    return None


def work_item_title(work_item_type: str | None) -> str:
    if work_item_type == "agent_progress":
        return "Agent 过程"
    if work_item_type == "tool_execution":
        return "工具执行"
    title = capability_display_name(work_item_type)
    if title:
        return title
    return "Agent 过程"


def format_elapsed_seconds(total_seconds: int) -> str:
    seconds = max(0, int(total_seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    return f"{minutes}m {remaining_seconds:02d}s"


def stable_event_id(thread_id: str, event_type: str, *parts: Any) -> str:
    raw = "|".join([thread_id, event_type, *[str(part or "") for part in parts]])
    return f"evt_{short_hash(raw)}"


def event_id_for_ordinal(run_id: str, ordinal: int) -> str:
    return f"evt_{run_id}_{ordinal:04d}"


def stable_token(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}_{short_hash(raw)}"


def short_hash(value: str) -> str:
    return sha1(value.encode("utf-8")).hexdigest()[:16]

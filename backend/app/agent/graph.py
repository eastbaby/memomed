import json
from inspect import isawaitable
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent.hitl.router import (
    route_after_human_interrupt,
    route_after_tool_result,
    tool_result_needs_interrupt,
)
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.tool_runtime import execute_tool_call
from app.agent.tools.registry import CONTINUATION_HANDLERS, TOOL_SPECS, TOOLS
from app.agent.llm import get_openai_llm_stream


TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
MAX_TOOL_CALL_ROUNDS_WITHOUT_FINAL_ANSWER = 3


async def call_model(state: AgentState) -> dict[str, Any]:
    llm = get_openai_llm_stream()
    latest_user_turn_key = _latest_user_message_text(state.get("messages", []))
    system_prompt = _system_prompt_with_state(
        SYSTEM_PROMPT,
        state.get("handoff_context"),
        state.get("agent_context") or {},
        state.get("satisfied_capabilities") or {},
        state.get("tool_observations") or [],
    )
    messages = _messages_for_model(list(state.get("messages", [])), handoff_context=state.get("handoff_context"))
    response = await llm.bind_tools(TOOLS).ainvoke(
        [{"role": "system", "content": system_prompt}] + messages
    )
    if _contains_fake_tool_call_text(response):
        response = await llm.bind_tools(TOOLS).ainvoke(
            [{"role": "system", "content": _retry_prompt_without_fake_tool_calls(system_prompt)}] + messages
        )
    if _contains_fake_tool_call_text(response):
        return {
            "messages": [AIMessage(content="")],
            "response": "",
            "metadata": {"status": "llm_invalid_tool_call_text"},
        }
    return {
        "messages": [response],
        "response": getattr(response, "content", ""),
        "active_tool_turn_key": latest_user_turn_key,
        "active_tool_call_count": _active_tool_call_count_for_turn(state, latest_user_turn_key),
    }


def tools_condition(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "final_answer" if _tool_call_rounds_exhausted(state) else "tools"
    return "final_answer"


async def run_tools(state: AgentState) -> dict[str, Any]:
    last_message = state["messages"][-1]
    tool_messages: list[ToolMessage] = []
    for tool_call in getattr(last_message, "tool_calls", []) or []:
        tool_name = tool_call.get("name")
        tool_call_id = tool_call.get("id") or tool_name or "tool_call"
        _emit_process_step(
            f"正在调用工具：{_tool_display_name(tool_name)}。",
            step_type="tool.started",
            title="工具调用",
            payload={"tool_name": tool_name, "phase": "started"},
        )
        result = await execute_tool_call(
            tool_call,
            state,
            tools_by_name=TOOLS_BY_NAME,
            tool_specs=TOOL_SPECS,
        )
        _emit_process_step(
            _tool_result_summary(result),
            step_type=_tool_result_step_type(result),
            title=_process_event_title(_process_event_type(result)),
            payload={
                "tool_name": tool_name,
                "phase": "completed",
                "status": result.get("status"),
            },
        )
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                name=tool_name,
                tool_call_id=tool_call_id,
            )
        )
    return {
        "messages": tool_messages,
        "active_tool_call_count": _active_tool_call_count_for_turn(
            state, _latest_user_message_text(state.get("messages", []))
        )
        + len(tool_messages),
    }


def inspect_tool_result(state: AgentState) -> dict[str, Any]:
    tool_observation = _latest_tool_observation(state.get("messages", []))
    tool_result = (tool_observation or {}).get("result")
    if tool_result_needs_interrupt(tool_result):
        interaction = dict(tool_result.get("interaction") or {})
        pending_action = tool_result.get("pending_action")
        if pending_action:
            interaction["pending_action"] = pending_action
        return {
            "pending_action": pending_action,
            "interaction": interaction,
            "process_events": [
                {"step_type": "runtime.note", "text": tool_result.get("message", "需要用户确认。")}
            ],
        }
    updates: dict[str, Any] = {
        "pending_action": None,
        "interaction": None,
    }
    if tool_observation:
        normalized_observation = _normalized_tool_observation(tool_observation)
        updates.update(
            {
                "tool_observations": [normalized_observation],
                "handoff_context": _format_tool_observation(normalized_observation),
                "agent_context": _merge_agent_context(
                    state.get("agent_context") or {},
                    normalized_observation,
                ),
                "satisfied_capabilities": _merge_satisfied_capabilities(
                    state.get("satisfied_capabilities") or {},
                    normalized_observation,
                    _latest_user_message_text(state.get("messages", [])),
                ),
            }
        )
    return updates


def human_interrupt(state: AgentState) -> dict[str, Any]:
    user_decision = interrupt(state.get("interaction") or {})
    return {"user_decision": user_decision}


async def continue_pending_action(state: AgentState) -> dict[str, Any]:
    pending_action = state.get("pending_action") or {}
    _emit_process_step(
        "正在处理你的确认结果。",
        step_type="runtime.note",
        title="继续执行",
        payload={
            "phase": "resume_started",
            "continuation_tool": pending_action.get("continuation_tool"),
        },
    )
    result = await _run_continuation_handler(pending_action, state.get("user_decision") or {})

    if tool_result_needs_interrupt(result):
        _emit_process_step(
            result.get("message", "还需要补充确认信息。"),
            step_type="interrupt.requested",
            title="需要补充信息",
            payload={"phase": "resume_needs_input"},
        )
        next_interaction = dict(result.get("interaction") or {})
        next_pending_action = result.get("pending_action")
        if next_pending_action:
            next_interaction["pending_action"] = next_pending_action
        user_decision = interrupt(next_interaction)
        result = await _run_continuation_handler(next_pending_action or {}, user_decision)

    _emit_process_step(
        result["message"],
        step_type=_tool_result_step_type(result),
        title=_process_event_title(_process_event_type(result)),
        payload={
            "phase": "resume_completed",
            "status": result.get("status"),
        },
    )
    continuation_observation = _normalized_tool_observation(
        {
            "tool_name": pending_action.get("continuation_tool") or "continuation",
            "capability": _continuation_capability(pending_action),
            "result": result,
        }
    )
    return {
        "process_events": [{"step_type": _tool_result_step_type(result), "text": result["message"]}],
        "pending_action": None,
        "interaction": None,
        "response": result["message"],
        "handoff_context": _format_tool_observation(continuation_observation),
        "tool_observations": [continuation_observation],
        "agent_context": _merge_agent_context(state.get("agent_context") or {}, continuation_observation),
        "satisfied_capabilities": _merge_satisfied_capabilities(
            state.get("satisfied_capabilities") or {},
            continuation_observation,
            _latest_user_message_text(state.get("messages", [])),
        ),
        "active_tool_call_count": 0,
        "metadata": {"status": result.get("status")},
    }


async def _run_continuation_handler(pending_action: dict[str, Any], user_decision: dict[str, Any]) -> dict[str, Any]:
    continuation_tool = pending_action.get("continuation_tool")
    handler = CONTINUATION_HANDLERS.get(continuation_tool)
    if handler is None:
        return {
            "status": "error",
            "message": f"未注册续接动作：{continuation_tool}",
            "data": {},
        }
    result = handler(pending_action, user_decision)
    if isawaitable(result):
        result = await result
    return result


def _process_event_type(result: dict[str, Any]) -> str:
    return "error" if result.get("status") == "error" else "tool_result"


def _tool_result_step_type(result: dict[str, Any]) -> str:
    return "tool.error" if result.get("status") == "error" else "tool.observation"


def _system_prompt_with_state(
    base_prompt: str,
    handoff_context: str | None,
    agent_context: dict[str, Any],
    satisfied_capabilities: dict[str, Any],
    tool_observations: list[dict[str, Any]],
) -> str:
    additions: list[str] = []
    if agent_context:
        additions.append(
            "当前 Agent 已确认的结构化上下文如下："
            f"{json.dumps(agent_context, ensure_ascii=False, sort_keys=True)}\n"
            "后续回答和工具调用应优先复用这些上下文，不要重复询问已经确认的信息。"
        )
    if satisfied_capabilities:
        additions.append(
            "本轮已经满足的能力如下："
            f"{json.dumps(satisfied_capabilities, ensure_ascii=False, sort_keys=True)}\n"
            "如果能力已经满足，不要为了同一个子目标重复调用同一个工具。"
        )
    if tool_observations:
        additions.append(
            "最近工具观察结果如下："
            f"{json.dumps(tool_observations[-3:], ensure_ascii=False, sort_keys=True)}\n"
            "必须基于最新工具观察结果继续推理；如果工具返回 capability_missing，请直接向用户说明该能力尚未接入。"
        )
    if handoff_context:
        additions.append(
            "刚刚完成的工具或续接动作结果如下："
            f"{handoff_context}\n"
            "请基于这个结果继续完成用户原始请求，并返回面向用户的最终回复。"
            "如果后续查询或入库工具尚未实现，请明确说明当前缺少对应工具，不要返回空内容。"
        )
    return f"{base_prompt}\n\n" + "\n\n".join(additions) if additions else base_prompt


def _retry_prompt_without_fake_tool_calls(system_prompt: str) -> str:
    return (
        f"{system_prompt}\n\n"
        "上一次输出包含了用户可见的伪工具调用文本，这是无效输出。"
        "请重新回答：只能输出普通中文自然语言；"
        "不要输出 <tool_call>、</tool_call>、JSON、函数名、parameters 或任何未注册工具名。"
    )


def _subject_from_tool_result(result: dict[str, Any]) -> dict[str, Any] | None:
    patient = (result.get("data") or {}).get("patient")
    if not isinstance(patient, dict):
        return None
    return {
        key: value
        for key, value in patient.items()
        if key in {"subject_id", "patient_code", "display_name", "patient_type", "patient_name"} and value is not None
    }


def _latest_user_message_text(messages: list) -> str | None:
    for message in reversed(messages):
        if isinstance(message, dict):
            if message.get("role") == "user":
                content = message.get("content")
                return content if isinstance(content, str) else None
            continue
        if getattr(message, "type", None) == "human":
            content = getattr(message, "content", None)
            return content if isinstance(content, str) else None
    return None


def _contains_fake_tool_call_text(message: Any) -> bool:
    if getattr(message, "tool_calls", None):
        return False
    content = getattr(message, "content", "")
    if isinstance(content, list):
        content = "".join(_content_part_text(part) for part in content)
    if not isinstance(content, str):
        return False
    lowered = content.lower()
    return any(
        marker in lowered
        for marker in (
            "<tool_call",
            "</tool_call>",
            '"parameters"',
            '"name":',
        )
    )


def _content_part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        text = part.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _process_event_title(event_type: str) -> str:
    return "执行失败" if event_type == "error" else "工具结果"


def _emit_process_step(
    text: str,
    *,
    step_type: str,
    title: str = "思考过程",
    work_item_type: str = "subject_resolution",
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer(
        {
            "type": "process_step",
            "step_type": step_type,
            "title": title,
            "text": text,
            "work_item_type": work_item_type,
            "payload": payload or {},
        }
    )


def _tool_display_name(tool_name: str | None) -> str:
    if tool_name and tool_name in TOOL_SPECS:
        return TOOL_SPECS[tool_name].display_name
    return tool_name or "未知工具"


def _tool_result_summary(result: dict[str, Any]) -> str:
    message = str(result.get("message") or "")
    if message:
        return message
    status = result.get("status") or "unknown"
    return f"工具已返回状态：{status}。"


def final_answer(state: AgentState) -> dict[str, Any]:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return {"response": "", "metadata": {"status": "final_answer_missing"}}
    content = (
        last_message.content
        if isinstance(last_message, AIMessage)
        else state.get("response") or "处理完成。"
    )
    if not str(content or "").strip():
        return {"response": "", "metadata": {"status": "llm_empty_response"}}
    return {"response": content, "metadata": {"status": "completed"}}


def _tool_call_rounds_exhausted(state: AgentState) -> bool:
    return int(state.get("active_tool_call_count") or 0) >= MAX_TOOL_CALL_ROUNDS_WITHOUT_FINAL_ANSWER


def _messages_for_model(messages: list, *, handoff_context: str | None) -> list:
    if not handoff_context:
        return messages
    pending_tool_call_ids = _pending_interrupt_tool_call_ids(messages)
    if not pending_tool_call_ids:
        return messages
    return [
        message
        for message in messages
        if not _is_pending_interrupt_tool_trace(message, pending_tool_call_ids)
    ]


def _pending_interrupt_tool_call_ids(messages: list) -> set[str]:
    ids: set[str] = set()
    for message in messages:
        tool_call_id = _tool_message_id_if_pending_interrupt(message)
        if tool_call_id:
            ids.add(tool_call_id)
    return ids


def _is_pending_interrupt_tool_trace(message: Any, pending_tool_call_ids: set[str]) -> bool:
    tool_call_id = _tool_message_id_if_pending_interrupt(message)
    if tool_call_id in pending_tool_call_ids:
        return True
    return bool(_ai_message_tool_call_ids(message) & pending_tool_call_ids)


def _tool_message_id_if_pending_interrupt(message: Any) -> str | None:
    if isinstance(message, ToolMessage):
        result = _parse_tool_message_content(message.content)
        if tool_result_needs_interrupt(result):
            return getattr(message, "tool_call_id", None)
        return None
    if isinstance(message, dict) and message.get("role") == "tool":
        result = _parse_tool_message_content(message.get("content"))
        if tool_result_needs_interrupt(result):
            return message.get("tool_call_id")
    return None


def _ai_message_tool_call_ids(message: Any) -> set[str]:
    tool_calls = getattr(message, "tool_calls", None)
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls")
    if not tool_calls:
        return set()
    return {str(tool_call.get("id")) for tool_call in tool_calls if tool_call.get("id")}


def _active_tool_call_count_for_turn(state: AgentState, latest_user_turn_key: str | None) -> int:
    if state.get("active_tool_turn_key") != latest_user_turn_key:
        return 0
    return int(state.get("active_tool_call_count") or 0)


def _latest_tool_observation(messages: list) -> dict[str, Any] | None:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            result = _parse_tool_message_content(message.content)
            if result is None:
                return None
            return {"tool_name": getattr(message, "name", None), "result": result}
    return None


def _parse_tool_message_content(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalized_tool_observation(observation: dict[str, Any]) -> dict[str, Any]:
    tool_name = observation.get("tool_name")
    result = observation.get("result") or {}
    spec = TOOL_SPECS.get(str(tool_name or ""))
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    capability = observation.get("capability") or data.get("capability") or (spec.capability if spec else str(tool_name or "tool"))
    return {
        "tool_name": tool_name,
        "capability": capability,
        "status": result.get("status") or "unknown",
        "message": result.get("message") or "",
        "data": data,
    }


def _format_tool_observation(observation: dict[str, Any]) -> str:
    tool_name = observation.get("tool_name") or "工具"
    message = observation.get("message") or "工具已返回结果。"
    status = observation.get("status") or "unknown"
    capability = observation.get("capability") or "unknown"
    return f"{tool_name} 返回 {status}（能力：{capability}）：{message}"


def _merge_agent_context(context: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    merged = dict(context)
    patient = (observation.get("data") or {}).get("patient")
    if isinstance(patient, dict):
        merged["subject"] = {
            key: value
            for key, value in patient.items()
            if key in {"subject_id", "patient_code", "display_name", "patient_type", "patient_name"} and value is not None
        }
    return merged


def _continuation_capability(pending_action: dict[str, Any]) -> str | None:
    if pending_action.get("type") in {"confirm_patient", "create_subject_name"}:
        return "subject_resolution"
    return None


def _merge_satisfied_capabilities(
    satisfied_capabilities: dict[str, Any],
    observation: dict[str, Any],
    turn_key: str | None,
) -> dict[str, Any]:
    merged = dict(satisfied_capabilities)
    if observation.get("status") not in {"success", "already_satisfied"}:
        return merged
    capability = observation.get("capability")
    if not capability:
        return merged
    merged[str(capability)] = {
        "turn_key": turn_key,
        "message": observation.get("message"),
        "data": observation.get("data") or {},
    }
    return merged


graph = (
    StateGraph(AgentState)
    .add_node("call_model", call_model)
    .add_node("tools", run_tools)
    .add_node("inspect_tool_result", inspect_tool_result)
    .add_node("human_interrupt", human_interrupt)
    .add_node("continue_pending_action", continue_pending_action)
    .add_node("final_answer", final_answer)
    .add_edge(START, "call_model")
    .add_conditional_edges(
        "call_model", tools_condition, {"tools": "tools", "final_answer": "final_answer"}
    )
    .add_edge("tools", "inspect_tool_result")
    .add_conditional_edges(
        "inspect_tool_result",
        route_after_tool_result,
        {
            "human_interrupt": "human_interrupt",
            "call_model": "call_model",
        },
    )
    .add_conditional_edges(
        "human_interrupt",
        route_after_human_interrupt,
        {"continue_pending_action": "continue_pending_action", "call_model": "call_model"},
    )
    .add_edge("continue_pending_action", "call_model")
    .add_edge("final_answer", END)
    .compile(name="memomed_agent", checkpointer=InMemorySaver())
)

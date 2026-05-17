import json
from inspect import isawaitable
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.agent.hitl.router import (
    route_after_human_interrupt,
    route_after_tool_result,
    tool_result_needs_interrupt,
)
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.tools.registry import CONTINUATION_HANDLERS, TOOLS
from app.agent.llm import get_openai_llm_stream


async def call_model(state: AgentState) -> dict[str, Any]:
    llm = get_openai_llm_stream()
    response = await llm.bind_tools(TOOLS).ainvoke(
        [{"role": "system", "content": SYSTEM_PROMPT}] + list(state.get("messages", []))
    )
    return {"messages": [response], "response": getattr(response, "content", "")}


def tools_condition(state: AgentState) -> str:
    last_message = state["messages"][-1]
    return "tools" if getattr(last_message, "tool_calls", None) else "final_answer"


def inspect_tool_result(state: AgentState) -> dict[str, Any]:
    tool_result = _latest_tool_result(state.get("messages", []))
    if tool_result_needs_interrupt(tool_result):
        interaction = dict(tool_result.get("interaction") or {})
        pending_action = tool_result.get("pending_action")
        if pending_action:
            interaction["pending_action"] = pending_action
        return {
            "pending_action": pending_action,
            "interaction": interaction,
            "process_events": [
                {"type": "thinking", "text": tool_result.get("message", "需要用户确认。")}
            ],
        }
    return {"pending_action": None, "interaction": None}


def human_interrupt(state: AgentState) -> dict[str, Any]:
    user_decision = interrupt(state.get("interaction") or {})
    return {"user_decision": user_decision}


async def continue_pending_action(state: AgentState) -> dict[str, Any]:
    pending_action = state.get("pending_action") or {}
    result = await _run_continuation_handler(pending_action, state.get("user_decision") or {})

    if tool_result_needs_interrupt(result):
        next_interaction = dict(result.get("interaction") or {})
        next_pending_action = result.get("pending_action")
        if next_pending_action:
            next_interaction["pending_action"] = next_pending_action
        user_decision = interrupt(next_interaction)
        result = await _run_continuation_handler(next_pending_action or {}, user_decision)

    return {
        "messages": [AIMessage(content=result["message"])],
        "process_events": [{"type": _process_event_type(result), "text": result["message"]}],
        "pending_action": None,
        "interaction": None,
        "response": result["message"],
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


def final_answer(state: AgentState) -> dict[str, Any]:
    last_message = state["messages"][-1]
    content = (
        last_message.content
        if isinstance(last_message, AIMessage)
        else state.get("response") or "处理完成。"
    )
    return {"response": content, "metadata": {"status": "completed"}}


def _latest_tool_result(messages: list) -> dict[str, Any] | None:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            content = message.content
            if isinstance(content, dict):
                return content
            if not isinstance(content, str):
                return None
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


tool_node = ToolNode(TOOLS)

graph = (
    StateGraph(AgentState)
    .add_node("call_model", call_model)
    .add_node("tools", tool_node)
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

from typing import Any


def tool_result_needs_interrupt(tool_result: dict[str, Any] | None) -> bool:
    if not tool_result:
        return False
    return tool_result.get("status") in {
        "needs_user_confirmation",
        "needs_user_selection",
        "needs_user_input",
    }


def route_after_tool_result(state: dict[str, Any]) -> str:
    if state.get("interaction"):
        return "human_interrupt"
    if state.get("response"):
        return "final_answer"
    return "call_model"


def route_after_human_interrupt(state: dict[str, Any]) -> str:
    pending_action = state.get("pending_action") or {}
    return "continue_pending_action" if pending_action.get("id") else "call_model"

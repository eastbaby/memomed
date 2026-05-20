import operator
from typing import Annotated, Any

from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    messages: Annotated[list, operator.add]
    process_events: Annotated[list[dict[str, Any]], operator.add]
    tool_observations: Annotated[list[dict[str, Any]], operator.add]
    pending_action: dict[str, Any] | None
    interaction: dict[str, Any] | None
    user_decision: dict[str, Any] | None
    response: str | None
    handoff_context: str | None
    agent_context: dict[str, Any]
    satisfied_capabilities: dict[str, Any]
    active_tool_call_count: int
    active_tool_turn_key: str | None
    metadata: dict[str, Any]

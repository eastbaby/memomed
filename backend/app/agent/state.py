import operator
from typing import Annotated, Any

from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    messages: Annotated[list, operator.add]
    process_events: Annotated[list[dict[str, Any]], operator.add]
    pending_action: dict[str, Any] | None
    interaction: dict[str, Any] | None
    user_decision: dict[str, Any] | None
    response: str | None
    metadata: dict[str, Any]

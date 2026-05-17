from collections.abc import Awaitable, Callable
from typing import Any

from app.agent.tools.patient import commit_patient_selection, resolve_patient_tool


TOOLS = [resolve_patient_tool]

ContinuationHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


CONTINUATION_HANDLERS: dict[str, ContinuationHandler] = {
    "commit_patient_selection": commit_patient_selection,
}

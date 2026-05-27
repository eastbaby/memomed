from collections.abc import Awaitable, Callable
from typing import Any

from app.agent.tool_runtime import ToolSpec
from app.agent.tools.patient import commit_patient_selection, resolve_patient_tool
from app.agent.tools.records import query_health_records_tool


TOOLS = [resolve_patient_tool, query_health_records_tool]
TOOL_SPECS = {
    "resolve_patient_tool": ToolSpec(
        name="resolve_patient_tool",
        display_name="确认健康档案对象",
        capability="subject_resolution",
        reuse_when_satisfied=True,
    ),
    "query_health_records_tool": ToolSpec(
        name="query_health_records_tool",
        display_name="查询健康报告",
        capability="health_records_query",
        context_requirements=("subject_id",),
    ),
}

ContinuationHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


CONTINUATION_HANDLERS: dict[str, ContinuationHandler] = {
    "commit_patient_selection": commit_patient_selection,
}

CONTINUATION_CAPABILITIES = {
    "commit_patient_selection": "subject_resolution",
}


def capability_display_name(capability: str | None) -> str | None:
    if not capability:
        return None
    for spec in TOOL_SPECS.values():
        if spec.capability == capability:
            return spec.display_name
    return None


def continuation_capability(continuation_tool: str | None) -> str | None:
    if not continuation_tool:
        return None
    return CONTINUATION_CAPABILITIES.get(continuation_tool)

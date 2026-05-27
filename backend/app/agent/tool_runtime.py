import json
from dataclasses import dataclass
from hashlib import sha1
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    display_name: str
    capability: str
    reuse_when_satisfied: bool = False
    context_requirements: tuple[str, ...] = ()


async def execute_tool_call(
    tool_call: dict[str, Any],
    state: dict[str, Any],
    *,
    tools_by_name: dict[str, Any],
    tool_specs: dict[str, ToolSpec],
) -> dict[str, Any]:
    tool_name = tool_call.get("name")
    tool = tools_by_name.get(tool_name)
    if tool is None:
        return {"status": "error", "message": f"未注册工具：{tool_name}", "data": {}}

    spec = tool_specs.get(tool_name)
    if spec and _already_satisfied(spec, state, tool_call.get("args") or {}):
        return _already_satisfied_result(spec, state)

    args = _args_with_context(tool_call.get("args") or {}, state, spec)
    return await tool.ainvoke(args)


def _args_with_context(args: dict[str, Any], state: dict[str, Any], spec: ToolSpec | None) -> dict[str, Any]:
    enriched = dict(args)
    if not spec:
        return enriched
    for requirement in spec.context_requirements:
        if enriched.get(requirement):
            continue
        value = _resolve_context_requirement(requirement, state)
        if value is not None:
            enriched[requirement] = value
    return enriched


def _resolve_context_requirement(requirement: str, state: dict[str, Any]) -> Any:
    if requirement == "subject_id":
        return _resolved_subject_id(state)
    return None


def _resolved_subject_id(state: dict[str, Any]) -> str | None:
    subject = (state.get("agent_context") or {}).get("subject")
    if isinstance(subject, dict) and subject.get("subject_id"):
        return str(subject["subject_id"])

    subject_resolution = (state.get("satisfied_capabilities") or {}).get("subject_resolution") or {}
    data = subject_resolution.get("data") if isinstance(subject_resolution, dict) else None
    patient = data.get("patient") if isinstance(data, dict) else None
    if isinstance(patient, dict) and patient.get("subject_id"):
        return str(patient["subject_id"])
    return None


def _already_satisfied(spec: ToolSpec, state: dict[str, Any], args: dict[str, Any]) -> bool:
    if not spec.reuse_when_satisfied:
        return False
    satisfied_capability = (state.get("satisfied_capabilities") or {}).get(spec.capability)
    if not satisfied_capability:
        return False
    return satisfied_capability.get("turn_key") == _latest_user_message_text(state.get("messages", []))


def _already_satisfied_result(spec: ToolSpec, state: dict[str, Any]) -> dict[str, Any]:
    satisfied_capability = (state.get("satisfied_capabilities") or {}).get(spec.capability) or {}
    data = satisfied_capability.get("data") or {}
    patient = data.get("patient") if isinstance(data, dict) else None
    display_name = (patient or {}).get("display_name") or "当前结果"
    return {
        "status": "already_satisfied",
        "message": f"本轮已经完成{spec.display_name}：{display_name}。",
        "data": {
            "capability": spec.capability,
            "args_hash": _hash_json(data),
            **(data if isinstance(data, dict) else {}),
        },
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


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return sha1(payload.encode("utf-8")).hexdigest()[:12]

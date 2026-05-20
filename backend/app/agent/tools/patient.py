import json
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.agent.hitl.schemas import InteractionRequest, SelectOption
from app.agent.llm import get_openai_llm_non_stream
from app.agent.tools.schemas import PendingAction, ToolResult
from app.db import AsyncSessionLocal
from app.models.models import MmCareSubject, MmCareSubjectAlias
from app.subjects.schemas import SubjectCreateRequest
from app.subjects.service import DuplicateAliasError, create_subject


CREATE_SUBJECT_OPTIONS = [
    SelectOption(label="新建人物", value="create_patient"),
    SelectOption(label="新建宠物", value="create_pet"),
]


class SubjectCandidate(BaseModel):
    subject_id: str
    patient_code: str
    display_name: str
    patient_type: Literal["human", "pet"]
    patient_name: str | None = None
    aliases: list[str] = Field(default_factory=list)


class PatientGrounding(BaseModel):
    intent: Literal["human_health", "pet_health", "general_chat", "unknown"]
    resolution_status: Literal["resolved", "ambiguous", "not_applicable"]
    matched_subject_id: str | None = None
    candidate_subject_ids: list[str] = Field(default_factory=list)
    patient_code: str | None = None
    display_name: str | None = None
    patient_type: Literal["human", "pet"] | None = None
    species: str | None = None
    confidence: Literal["high", "medium", "low"]
    reason: str
    next_action: Literal["continue", "ask_patient_selection", "ask_clarifying_question"]


def _dump_result(result: ToolResult) -> dict:
    return result.model_dump(mode="json", exclude_none=True)


@tool
async def resolve_patient_tool(user_text: str) -> dict:
    """判断本轮聊天要管理哪个家庭成员或宠物的健康档案。"""
    text = user_text.strip()
    candidates = await list_subject_candidates()
    grounding = _first_person_grounding(text, candidates)
    if grounding:
        return _tool_result_from_grounding(text, grounding, candidates)
    grounding = await classify_patient_grounding(text, candidates)
    return _tool_result_from_grounding(text, grounding, candidates)


async def list_subject_candidates(owner_user_id: str | None = None) -> list[SubjectCandidate]:
    async with AsyncSessionLocal() as session:
        statement = select(MmCareSubject).where(MmCareSubject.status == "active")
        if owner_user_id:
            statement = statement.where(MmCareSubject.owner_user_id == owner_user_id)
        else:
            statement = statement.where(MmCareSubject.owner_user_id == "default")
        statement = statement.order_by(MmCareSubject.subject_type.asc(), MmCareSubject.display_name.asc())
        subjects = (await session.execute(statement)).scalars().all()

        subject_ids = [subject.id for subject in subjects]
        alias_rows = []
        if subject_ids:
            alias_statement = (
                select(MmCareSubjectAlias)
                .where(MmCareSubjectAlias.subject_id.in_(subject_ids))
                .where(MmCareSubjectAlias.status == "active")
                .order_by(MmCareSubjectAlias.alias.asc())
            )
            alias_rows = (await session.execute(alias_statement)).scalars().all()

    aliases_by_subject = _group_aliases_by_subject(alias_rows)
    return [
        SubjectCandidate(
            subject_id=str(subject.id),
            patient_code=str(subject.id),
            display_name=subject.display_name,
            patient_type=subject.subject_type,
            patient_name=subject.legal_name,
            aliases=_build_aliases(subject, aliases_by_subject.get(str(subject.id), [])),
        )
        for subject in subjects
    ]


async def classify_patient_grounding(
    user_text: str,
    candidates: list[SubjectCandidate],
) -> PatientGrounding:
    """用受限 LLM 分类器判断健康档案主体。"""
    llm = get_openai_llm_non_stream().with_structured_output(PatientGrounding)
    candidate_payload = [candidate.model_dump(mode="json") for candidate in candidates]
    try:
        result = await llm.ainvoke(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 Memomed 的 patient grounding 分类器。"
                        "你只输出结构化结果，不回答用户。"
                        "目标是根据现有健康档案主体列表，判断用户要管理的是哪个人或哪只宠物。"
                        "不要把所有格“我的”直接理解为用户本人；例如“我的猫咪”主体是宠物猫。"
                        "但第一人称“我、本人、自己、我上次、我之前”通常表示用户本人；"
                        "如果候选列表里存在 display_name 或 alias 为“我”的人物主体，应优先高置信匹配该主体。"
                        "只有当主体能和候选列表中的 subject_id 唯一匹配时，resolution_status=resolved 并填写 matched_subject_id。"
                        "如果用户只说家人、这份报告、帮忙存一下但没有主体，resolution_status=ambiguous。"
                        "如果和人或宠物健康档案无关，resolution_status=not_applicable。"
                        "如果用户提到的宠物或成员不在候选列表里，不要编造 subject_id；应返回 ambiguous，next_action=ask_patient_selection。"
                        f"现有候选主体 JSON：{json.dumps(candidate_payload, ensure_ascii=False)}"
                    ),
                },
                {"role": "user", "content": user_text},
            ]
        )
        if isinstance(result, PatientGrounding):
            return result
        if isinstance(result, dict):
            return PatientGrounding.model_validate(result)
    except (ValidationError, json.JSONDecodeError, ValueError):
        pass

    # LLM 输出异常时保守进入人工选择，不做粗暴关键词归属。
    return PatientGrounding(
        intent="unknown",
        resolution_status="ambiguous",
        confidence="low",
        reason="主体识别失败，保守请求用户确认。",
        next_action="ask_patient_selection",
    )


def _tool_result_from_grounding(
    user_text: str,
    grounding: PatientGrounding,
    candidates: list[SubjectCandidate],
) -> dict:
    matched_candidate = _find_candidate(grounding.matched_subject_id, candidates)
    if grounding.resolution_status == "resolved" and grounding.confidence == "high" and matched_candidate:
        return _dump_result(
            ToolResult(
                status="success",
                message=f"已识别这次管理对象是{matched_candidate.display_name}。",
                data={
                    "intent": grounding.intent,
                    "confidence": grounding.confidence,
                    "reason": grounding.reason,
                    "patient": {
                        "subject_id": matched_candidate.subject_id,
                        "patient_code": matched_candidate.patient_code,
                        "display_name": matched_candidate.display_name,
                        "patient_type": matched_candidate.patient_type,
                        "patient_name": matched_candidate.patient_name,
                    },
                },
            )
        )

    if grounding.resolution_status == "not_applicable":
        return _dump_result(
            ToolResult(
                status="not_applicable",
                message="这条消息没有指向需要管理的人或宠物健康档案。",
                data={
                    "intent": grounding.intent,
                    "confidence": grounding.confidence,
                    "reason": grounding.reason,
                },
            )
        )

    return _dump_result(
        ToolResult(
            status="needs_user_selection",
            message="需要确认本次健康档案的管理对象。",
            pending_action=PendingAction(
                id="pa_confirm_patient",
                type="confirm_patient",
                continuation_tool="commit_patient_selection",
                candidate_payload={
                    "original_text": user_text,
                    "grounding": grounding.model_dump(mode="json"),
                    "candidate_subject_ids": [candidate.subject_id for candidate in candidates],
                },
            ),
            interaction=InteractionRequest(
                type="select_one",
                title="这次要管理谁或哪只宠物的健康档案？",
                description=_selection_description(candidates),
                options=_selection_options(candidates),
            ),
        )
    )


def _find_candidate(subject_id: str | None, candidates: list[SubjectCandidate]) -> SubjectCandidate | None:
    if not subject_id:
        return None
    return next((candidate for candidate in candidates if candidate.subject_id == subject_id), None)


def _first_person_grounding(user_text: str, candidates: list[SubjectCandidate]) -> PatientGrounding | None:
    self_candidate = next(
        (
            candidate
            for candidate in candidates
            if candidate.patient_type == "human" and "我" in {candidate.display_name, *candidate.aliases}
        ),
        None,
    )
    if not self_candidate:
        return None
    if not _looks_like_first_person_subject(user_text):
        return None
    return PatientGrounding(
        intent="human_health",
        resolution_status="resolved",
        matched_subject_id=self_candidate.subject_id,
        patient_code=self_candidate.patient_code,
        display_name=self_candidate.display_name,
        patient_type=self_candidate.patient_type,
        confidence="high",
        reason="用户使用第一人称主语描述自己的健康信息。",
        next_action="continue",
    )


def _looks_like_first_person_subject(user_text: str) -> bool:
    first_person_patterns = (
        "我上次",
        "我之前",
        "我最近",
        "我现在",
        "我去年",
        "我今年",
        "我吃",
        "我用",
        "我服",
        "我查",
        "我看",
    )
    return any(pattern in user_text for pattern in first_person_patterns)


def _selection_options(candidates: list[SubjectCandidate]) -> list[SelectOption]:
    return [
        SelectOption(
            label=_subject_option_label(candidate),
            value=f"subject:{candidate.subject_id}",
        )
        for candidate in candidates
    ] + CREATE_SUBJECT_OPTIONS


def _subject_option_label(candidate: SubjectCandidate) -> str:
    type_label = "宠物" if candidate.patient_type == "pet" else "成员"
    return f"{candidate.display_name}（{type_label}）"


def _selection_description(candidates: list[SubjectCandidate]) -> str:
    if candidates:
        return "我先把健康档案对象对齐，避免把报告或健康信息存到错误的人或宠物名下。"
    return "现有档案里没有足够明确的对象，请选择新建人物/宠物后继续。"


def _group_aliases_by_subject(alias_rows: list[MmCareSubjectAlias]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for alias_row in alias_rows:
        grouped.setdefault(str(alias_row.subject_id), []).append(alias_row.alias)
    return grouped


def _build_aliases(subject: MmCareSubject, alias_values: list[str]) -> list[str]:
    aliases = {subject.display_name, *alias_values}
    if subject.legal_name:
        aliases.add(subject.legal_name)
    return [alias for alias in aliases if alias]


async def commit_patient_selection(
    pending_action: dict,
    user_decision: dict,
) -> dict:
    if pending_action.get("type") == "create_subject_name":
        return await _commit_create_subject(pending_action, user_decision)

    value = user_decision.get("value")
    label = user_decision.get("label") or _label_from_decision_value(value)

    if value in {"create_patient", "create_pet"}:
        subject_type = "pet" if value == "create_pet" else "human"
        type_label = "宠物" if subject_type == "pet" else "人物"
        return _dump_result(
            ToolResult(
                status="needs_user_input",
                message=f"请先输入要新建的{type_label}名称。",
                pending_action=PendingAction(
                    id=f"pa_create_{subject_type}",
                    type="create_subject_name",
                    continuation_tool="commit_patient_selection",
                    candidate_payload={
                        **(pending_action.get("candidate_payload") or {}),
                        "subject_type": subject_type,
                    },
                ),
                interaction=InteractionRequest(
                    type="text_input",
                    title=f"新建{type_label}档案",
                    description=f"请输入这个{type_label}在 Memomed 里展示的名称，之后也可以在成员管理页修改。",
                    placeholder="例如：妈妈" if subject_type == "human" else "例如：小橘",
                ),
            )
        )

    return _dump_result(
        ToolResult(
            status="success",
            message=f"已确认这次管理对象是{label}。",
            data={
                "patient": {
                    "subject_id": _subject_id_from_decision_value(value),
                    "patient_code": value,
                    "display_name": label,
                },
                "source": pending_action.get("candidate_payload", {}),
            },
        )
    )


async def _commit_create_subject(pending_action: dict, user_decision: dict) -> dict:
    candidate_payload = pending_action.get("candidate_payload") or {}
    subject_type = candidate_payload.get("subject_type") or "human"
    display_name = str(user_decision.get("value") or "").strip()
    if not display_name:
        return _dump_result(
            ToolResult(
                status="error",
                message="新建档案失败：名称不能为空。",
                data={},
            )
        )

    grounding = candidate_payload.get("grounding") or {}
    species = grounding.get("species") if subject_type == "pet" else None
    relation_type = "pet" if subject_type == "pet" else None

    try:
        subject = await create_subject(
            SubjectCreateRequest(
                subject_type=subject_type,
                display_name=display_name,
                alias=display_name,
                relation_type=relation_type,
                species=species,
            )
        )
    except DuplicateAliasError:
        return _dump_result(
            ToolResult(
                status="error",
                message=f"新建档案失败：别名“{display_name}”已经被其他成员或宠物使用。",
                data={},
            )
        )

    type_label = "宠物" if subject.subject_type == "pet" else "人物"
    return _dump_result(
        ToolResult(
            status="success",
            message=f"已新建{type_label}档案：{subject.display_name}，并确认这次管理对象是{subject.display_name}。",
            data={
                "patient": {
                    "subject_id": subject.id,
                    "patient_code": subject.id,
                    "display_name": subject.display_name,
                    "patient_type": subject.subject_type,
                    "patient_name": subject.legal_name,
                },
                "source": candidate_payload,
            },
        )
    )


def _subject_id_from_decision_value(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("subject:"):
        return value.removeprefix("subject:")
    return None


def _label_from_decision_value(value: Any) -> str:
    labels = {
        "create_patient": "新建人物",
        "create_pet": "新建宠物",
    }
    return labels.get(str(value), "未知对象")

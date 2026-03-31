import copy
import json
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field, ValidationError

from app.agent.utils.llm import (
    get_openai_llm_non_stream,
    get_openai_llm_stream,
    get_sft_llm_non_stream,
)
from app.agent.utils.state import AgentState
from app.agent.utils.tools import get_tools

from .hitl import (
    HITLRequest,
    HITLActionRequest,
    HITLReviewConfig,
    HITLDecision,
    HITLResumePayload,
)
from .rag import ReportMetadata, prepare_medical_report, store_prepared_medical_report


class HumanImageStoreItem(BaseModel):
    """单个图片存储决策"""

    image_index: int
    store_decision: Literal["store_pending", "no_store"]


class HumanImageStoreList(BaseModel):
    """图片存储决策列表"""

    human_image_store_list: list[HumanImageStoreItem]


class ReportImageFeature(BaseModel):
    """单图特征提取结果"""

    image_index: int
    grouping_key: str = Field(..., description="属于同一份报告的图片应共享同一个 key")
    report_type: str | None = Field(default=None, description="推测报告类型")
    page_number_hint: int | None = Field(default=None, description="推测页码")
    order_confidence: Literal["high", "medium", "low"] = Field(default="low")
    reasoning: str | None = Field(default=None, description="简短说明判断依据")


class ReportUploadGroup(BaseModel):
    """多图自动分组与页序推断结果（LLM 结构化输出格式）"""

    group_id: str
    image_indices: list[int]
    ordered_image_indices: list[int]
    report_type: str | None = None
    confidence: Literal["high", "medium", "low"] = Field(default="low")
    needs_confirmation: bool = True
    reasoning: str | None = None
    # 上传决策字段，贯穿整个报告上传流程：
    #   None  = 尚未决定（needs_confirmation=True 时的初始值，等待用户在 confirm_report_uploads 节点确认）
    #   True  = 确认上传（高置信度自动确认，或用户手动批准）
    #   False = 拒绝上传（用户手动拒绝）
    selected: bool | None = None


class ReportUploadAnalysis(BaseModel):
    """多图报告分析结果"""

    features: list[ReportImageFeature]
    groups: list[ReportUploadGroup]


# ---------------------------------------------------------------------------
async def process_input(state: AgentState) -> dict:
    """处理用户输入，提取图片并生成后续报告入库计划。"""
    messages = state["messages"]
    question_message_content = copy.deepcopy(messages[-1]["content"])

    # step1 把messages中type: image的消息转换为type:image_url格式并存储到human_image_list中 （注意：只处理最近一次用户输入的图片消息）
    human_image_list: list[dict[str, Any]] = []
    for item in question_message_content:
        if isinstance(item, dict) and item.get("type") == "image":
            item["type"] = "image_url"
            item["image_url"] = {"url": f"data:{item['mimeType']};base64,{item['data']}"}
            del item["data"]
            human_image_list.append(item)

    # step2 判断是否需要存储图片到数据库中，生成 human_image_store_list
    human_image_store_list = await _decide_whether_store_image(
        question_message_content, human_image_list
    )
    report_upload_plans = await _plan_report_uploads(
        question_message_content=question_message_content,
        human_image_list=human_image_list,
        human_image_store_list=human_image_store_list,
    )

    return {
        "messages": [],
        "question_message_content": question_message_content,
        "human_image_list": human_image_list,
        "human_image_store_list": human_image_store_list,
        "report_upload_plans": report_upload_plans,
    }


def route_after_process_input(state: AgentState) -> str:
    """process_input 之后的路由节点，根据 report_upload_plans 的状态决定下一步。

    路由优先级：
      1. 有任何分组 needs_confirmation=True 且 selected=None → 先让用户确认分组
      2. 有任何分组 selected=True → 用户已确认，去执行上传准备
      3. 否则 → 没有需要上传的报告，直接进入正常对话
    """
    plans = state.get("report_upload_plans") or []
    if any(plan.get("needs_confirmation") and plan.get("selected") is None for plan in plans):
        return "confirm_report_uploads"
    if any(plan.get("selected", False) for plan in plans):
        return "prepare_report_uploads"
    return "call_model"


def confirm_report_uploads(state: AgentState) -> dict:
    """HITL 确认节点：向前端发起 interrupt，等待用户对分组方案做出决策。"""
    plans = state.get("report_upload_plans") or []
    # interrupt 会暂停 graph 执行并将 payload 推送给前端，前端 resume 时携带 decision
    decision = interrupt(_build_report_upload_interrupt_payload(plans))
    updated_plans = _apply_report_upload_confirmation(plans, decision)
    return {"report_upload_plans": updated_plans}


def route_after_confirm_report_uploads(state: AgentState) -> str:
    """确认分组方案后的路由。"""
    plans = state.get("report_upload_plans") or []
    if any(plan.get("selected") for plan in plans):
        return "prepare_report_uploads"
    return "call_model"


def _extract_conversation_context(messages: list, max_turns: int = 10) -> str | None:
    """从消息历史中提取纯文字内容，组成对话摘要供 LLM 参考。

    兼容 LangChain message 对象（AIMessage / HumanMessage）和字典两种格式。
    只保留包含文字内容的消息（跳过纯图片消息），并限制最近 max_turns 条，
    避免上下文过长消耗过多 token。
    """
    text_messages = []
    for msg in messages:
        # 兼容 LangChain message 对象（有 .type / .content 属性）和字典两种格式
        if hasattr(msg, "type"):
            role = msg.type  # "human" / "ai" / "tool"
            content = msg.content
        else:
            role = msg.get("type") or msg.get("role", "")
            content = msg.get("content", "")

        # 跳过 tool 消息（工具调用结果，对归属人判断无意义）
        if role == "tool":
            continue

        if isinstance(content, str) and content.strip():
            text_messages.append((role, content.strip()))
        elif isinstance(content, list):
            # 多模态消息：只提取其中的文字部分
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip()
            ]
            if text_parts:
                text_messages.append((role, " ".join(text_parts)))

    # 只保留最近 max_turns 条
    recent = text_messages[-max_turns:]
    if not recent:
        return None

    lines = []
    for role, text in recent:
        label = "用户" if role in ("human", "user") else "助手"
        lines.append(f"{label}：{text}")
    return "\n".join(lines)


async def prepare_report_uploads(state: AgentState) -> dict:
    """对每个 selected=True 的分组，调用 prepare_medical_report 提取报告结构化元数据。"""
    plans = copy.deepcopy(state.get("report_upload_plans") or [])
    if not plans:
        return {"report_upload_plans": []}

    # 提取对话历史中的文字内容，用于辅助 LLM 判断报告归属人
    # 仅取最近 10 条包含文字的消息，控制 token 用量
    conversation_context = _extract_conversation_context(state.get("messages") or [], max_turns=10)

    for plan in plans:
        # 只处理已被批准且尚未 prepare 的分组
        if not plan.get("selected"):
            continue
        if plan.get("prepared_report"):  # 已 prepare 过（如从 checkpoint 恢复），跳过
            continue

        image_urls = _collect_plan_image_urls(plan, state.get("human_image_list") or [])
        prepared_report = await prepare_medical_report(
            image_urls,
            conversation_context=conversation_context,
        )
        plan["prepared_report"] = prepared_report

    return {"report_upload_plans": plans}


def route_after_prepare_report_uploads(state: AgentState) -> str:
    """报告预处理后的路由。"""
    plans = state.get("report_upload_plans") or []
    if any(_plan_requires_metadata_confirmation(plan) for plan in plans):
        return "notify_metadata_confirmation"
    return "finalize_report_uploads"


def notify_metadata_confirmation(state: AgentState) -> dict:
    """发出一条 AI 消息提示用户核对解析结果，从而确保前端能正确显示挂载在该消息上的中断。"""
    return {"messages": [AIMessage(content="报告解析已由 AI 提取完成，请核对并更正以下信息：")]}


def confirm_report_metadata(state: AgentState) -> dict:
    """HITL 确认节点：等待用户对报告元数据做出决策。"""
    plans = state.get("report_upload_plans") or []
    decision = interrupt(_build_metadata_interrupt_payload(plans))
    updated_plans = _apply_metadata_confirmation(plans, decision)
    return {"report_upload_plans": updated_plans}


def route_after_confirm_report_metadata(state: AgentState) -> str:
    """确认元数据后的路由。"""
    plans = state.get("report_upload_plans") or []
    if any(plan.get("selected") for plan in plans):
        return "finalize_report_uploads"
    return "call_model"


async def finalize_report_uploads(state: AgentState) -> dict:
    """最终入库节点：将所有已批准(selected=True)的报告入库，并更新图片的最终存储状态。

    逻辑：
    1. 遍历所有上传计划。
    2. 对于用户拒绝的分组，将相关图片标记为 no_store。
    3. 对于已批准的分组，调用存储接口完成入库。
    4. 根据存储结果更新图片的成功/失败状态，并汇总成一条提示消息给用户。
    """
    plans = copy.deepcopy(state.get("report_upload_plans") or [])
    human_image_store_list = list(state.get("human_image_store_list") or [])

    for plan in plans:
        # 1-based 转 0-based 索引处理
        image_indices = plan.get("ordered_image_indices") or plan.get("image_indices") or []
        zero_based_indices = [max(index - 1, 0) for index in image_indices]

        # 如果该分组被拒绝上传，store status 改为 no_store
        if not plan.get("selected"):
            for index in zero_based_indices:
                # 之前标记为待存储的图片，现在明确标记为不存储
                if 0 <= index < len(human_image_store_list) and human_image_store_list[index] == "store_pending":
                    human_image_store_list[index] = "no_store"
            continue

        prepared_report = plan.get("prepared_report")
        if not prepared_report:
            continue

        try:
            # 调用 RAG 存储接口将结构化报告存入向量库
            store_result = await store_prepared_medical_report(prepared_report)
            plan["store_result"] = store_result
            # 更新图片状态为成功
            for index in zero_based_indices:
                if 0 <= index < len(human_image_store_list):
                    human_image_store_list[index] = "store_success"
        except Exception as exc:
            # 记录失败原因
            print(str(exc))
            plan["store_error"] = str(exc)
            # 更新图片状态为失败
            for index in zero_based_indices:
                if 0 <= index < len(human_image_store_list):
                    human_image_store_list[index] = "store_failed"

    # 生成汇报给用户的状态汇总文字
    status_message = _build_image_store_status_message(human_image_store_list, plans)
    return {
        "messages": [AIMessage(content=status_message)] if status_message else [],
        "human_image_store_list": human_image_store_list,
        "report_upload_plans": plans,
    }


async def _decide_whether_store_image(
    question_message_content: list, human_image_list: list
) -> list[Literal["store_pending", "no_store"]]:
    """判断是否需要存储图片到数据库。"""
    if not human_image_list:
        return []

    try:
        llm = get_openai_llm_non_stream()

        prompt = """你是一个智能助手，需要判断用户上传的图片是否需要存储到向量数据库中。

需要存储的条件：
1. 和体检、出院小结、检验报告等所有健康报告相关的所有报告（包括但不限于：体检报告、出院小结、检验报告、血常规、尿常规、肝功能、肾功能、血糖、血脂、血压、心电图、B超、超声、CT、核磁共振、病理报告等）
2. 用户强烈要求存储到RAG/向量数据库中

不需要存储的条件：1
1. 日常生活照片（风景、人物、食物等与健康报告无关的照片）
2. 无关的图片或截图

请根据以上条件判断是否需要存储图片。按给定的human_image_list顺序返回结果。
必须输出合法的 JSON，并严格匹配给定 schema，不要输出额外说明。
"""

        structured_llm = llm.with_structured_output(HumanImageStoreList)
        text_content = [
            item
            for item in question_message_content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        new_content = text_content + human_image_list

        response = await structured_llm.ainvoke(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": new_content},
            ]
        )
        return [item.store_decision for item in response.human_image_store_list]
    except Exception as e:
        raise ValueError(f"分析图片失败，{str(e)}")


async def _plan_report_uploads(
    question_message_content: list,
    human_image_list: list,
    human_image_store_list: list[str],
) -> list[dict[str, Any]]:
    pending_indices = [
        index + 1
        for index, decision in enumerate(human_image_store_list)
        if decision == "store_pending" and index < len(human_image_list)
    ]
    if not pending_indices:
        return []

    if len(pending_indices) == 1:
        # 单张图片无歧义，无需人工确认，直接 selected=True
        image_index = pending_indices[0]
        return [
            ReportUploadGroup(
                group_id="report_1",
                image_indices=[image_index],
                ordered_image_indices=[image_index],
                reasoning="单张医疗报告图片，直接按单份报告处理。",
                needs_confirmation=False,
                selected=True,  # 单张无歧义，跳过用户确认直接入库
            ).model_dump(mode="json")
        ]

    try:
        llm = get_openai_llm_non_stream()
        structured_llm = llm.with_structured_output(ReportUploadAnalysis)
        text_content = [
            item
            for item in question_message_content
            if isinstance(item, dict) and item.get("type") == "text"
        ]

        analysis = await structured_llm.ainvoke(
            [
                {
                    "role": "system",
                    "content": """你是医疗报告图片编排助手。

任务：
1. 先对每张图片抽取单图特征。
2. 再把属于同一份医疗报告的图片自动分组。
3. 再推断每组图片的页序。
4. 如果有任何不确定性，needs_confirmation 必须设为 true。

要求：
1. 只分析用户上传的医疗报告图片。
2. image_indices 和 ordered_image_indices 都使用 1-based 索引。
3. 同一组的 ordered_image_indices 必须是 image_indices 的重排结果。
4. confidence 低或存在疑问时，needs_confirmation 设为 true。
5. 必须输出合法 JSON，并严格匹配给定 schema，不要输出额外说明。""",
                },
                {"role": "user", "content": text_content + human_image_list},
            ]
        )

        plans: list[dict[str, Any]] = []
        pending_set = set(pending_indices)
        for group in analysis.groups:
            # 过滤掉包含非 pending 图片的分组（防止把已决策的图片重复处理）
            if not set(group.image_indices).issubset(pending_set):
                continue

            # selected 初始值由 needs_confirmation 决定：
            #   - 高置信度（needs_confirmation=False）→ True，跳过人工确认直接入库
            #   - 低置信度或有歧义（needs_confirmation=True）→ None，等待 confirm_report_uploads 节点
            group.selected = None if group.needs_confirmation else True
            # ordered_image_indices 若 LLM 未返回，则降级为原始顺序
            group.ordered_image_indices = group.ordered_image_indices or group.image_indices

            plan = group.model_dump(mode="json")  # 把 ReportUploadGroup 的所有字段序列化为 dict
            # features 不在 ReportUploadGroup schema 中，作为运行时附加字段写入
            plan["features"] = [
                feature.model_dump(mode="json")
                for feature in analysis.features
                if feature.image_index in group.image_indices
            ]
            plans.append(plan)

        if plans:
            return plans
    except Exception:
        pass

    # LLM 分析失败时的兜底方案：把所有 pending 图片合并为一组，强制走人工确认流程
    return [
        ReportUploadGroup(
            group_id="report_1",
            image_indices=pending_indices,
            ordered_image_indices=pending_indices,
            reasoning="检测到多张疑似医疗报告图片，先按单组顺序处理，待人工确认。",
            needs_confirmation=True,
            selected=None,  # 须人工确认，初始为 None
        ).model_dump(mode="json")
    ]


async def call_model(state: AgentState) -> dict:
    """调用语言模型。"""
    llm = get_openai_llm_stream()
    tools = get_tools()
    answer_keypoints = []
    answer_keypoints_text = "；".join(answer_keypoints) if answer_keypoints else "无"

    system_prompt = f"""你是一个专业的健康就医管理助手，专注于帮助用户管理健康相关信息和提供医疗建议。

你的职责包括：
1. 回答用户关于健康、医疗、就医相关的问题
2. 帮助用户管理和解读医疗报告
3. 提供合理的健康建议和就医指导
4. 引导用户讨论健康就医相关话题

请注意：
- 你不是医生，不能提供具体的医疗诊断和治疗方案
- 对于严重的健康问题，请建议用户咨询专业医生
- 保持专业、友好、耐心的态度
- 如果下面提供了回答关键点，最终答复必须自然覆盖这些关键点
- 不要输出 JSON，不要显式说“关键点如下”

回答关键点：
{answer_keypoints_text}
"""

    system_message = {"role": "system", "content": system_prompt}
    messages = state["messages"]
    messages_copy = copy.deepcopy(messages)

    for msg in messages_copy:
        if "content" in msg and isinstance(msg["content"], list):
            for item in msg["content"]:
                if isinstance(item, dict) and item.get("type") == "image":
                    item["type"] = "image_url"
                    item["image_url"] = {"url": f"data:{item['mimeType']};base64,{item['data']}"}
                    del item["data"]

    llm_with_tools = llm.bind_tools(tools)
    response = await llm_with_tools.ainvoke([system_message] + messages_copy)
    return {
        "messages": [response],
        "response": response.content,
        "answer_keypoints": answer_keypoints,
    }


class MedicalAgentTask(BaseModel):
    """医疗助手 Agent 任务编排输出格式（SFT 输出结构）"""

    answer_keypoints: list[str] = Field(..., description="回答关键点，给用户的回答中必须包含的内容")


def tools_condition(state: AgentState) -> str:
    """决定是否继续执行。"""
    messages = state["messages"]
    last_message = messages[-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


async def _extract_answer_keypoints(state: AgentState) -> list[str]:
    """使用 SFT 模型提取最终回答必须覆盖的关键点。"""
    question = _get_latest_user_question(state)
    if not question:
        return []

    llm = get_sft_llm_non_stream()
    response = await llm.ainvoke(
        [
            {"role": "user", "content": f"用户的问题是：{question}, 请生成回答关键要点"},
        ]
    )
    raw_content = response.content if isinstance(response.content, str) else str(response.content)
    content = raw_content.strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()

    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start == -1 or end == 0 or start >= end:
            return []

        parsed_json = json.loads(content[start:end])
        parsed_task = MedicalAgentTask.model_validate(parsed_json)
        return parsed_task.answer_keypoints
    except (json.JSONDecodeError, ValidationError):
        return []


def generate_response(state: AgentState) -> dict:
    """生成最终响应。"""
    messages = state["messages"]
    last_message = messages[-1]

    return {
        "response": last_message.content if isinstance(last_message, AIMessage) else "处理完成",
        "metadata": {"status": "completed", "answer_keypoints": state.get("answer_keypoints", [])},
    }


tool_node = ToolNode(get_tools())


def _build_report_upload_interrupt_payload(plans: list[dict[str, Any]]) -> dict[str, Any]:
    """构造符合 agent-chat-ui HITLRequest schema 的分组确认请求。

    action_requests: 每个待确认分组一个， args 内容即分组信息。
    review_configs: 每个分组允许 approve / reject。
    """
    pending = [p for p in plans if p.get("needs_confirmation") and p.get("selected") is None]
    return HITLRequest(
        action_requests=[
            HITLActionRequest(
                name=plan["group_id"],
                description=plan.get("reasoning") or "请确认该分组是否需要入库",
                args={
                    "image_indices": plan.get("ordered_image_indices") or plan.get("image_indices", []),
                    "report_type": plan.get("report_type"),
                },
            )
            for plan in pending
        ],
        review_configs=[
            HITLReviewConfig(
                action_name=plan["group_id"],
                allowed_decisions=["approve", "reject"],
            )
            for plan in pending
        ],
    ).model_dump(exclude_none=True)


def _apply_report_upload_confirmation(
    plans: list[dict[str, Any]], decision: Any
) -> list[dict[str, Any]]:
    """decision 格式为 agent-inbox 返回的 HITLResumePayload。"""
    updated_plans = copy.deepcopy(plans)

    # 小量兼容：非字典输入视为全部确认
    if not isinstance(decision, dict):
        for plan in updated_plans:
            if plan.get("needs_confirmation") and plan.get("selected") is None:
                plan["selected"] = True
        return updated_plans

    # 尝试解析为 HITLResumePayload
    try:
        resume = HITLResumePayload.model_validate(decision)
        decisions_by_name = {d.action_name: d for d in resume.decisions if d.action_name}
    except (ValidationError, Exception):
        # 解析失败则全部确认
        decisions_by_name = {}

    for plan in updated_plans:
        if not (plan.get("needs_confirmation") and plan.get("selected") is None):
            continue
        d = decisions_by_name.get(plan["group_id"])
        plan["selected"] = (d is None) or (d.type != "reject")
    return updated_plans


def _plan_requires_metadata_confirmation(plan: dict[str, Any]) -> bool:
    if not plan.get("selected"):
        return False
    prepared_report = plan.get("prepared_report") or {}
    report_metadata = prepared_report.get("report_metadata") or {}
    return (
        report_metadata.get("parse_status") == "needs_confirm"
        and not plan.get("metadata_confirmed")
    )


def _build_metadata_interrupt_payload(plans: list[dict[str, Any]]) -> dict[str, Any]:
    """构造符合 agent-chat-ui HITLRequest schema 的元数据确认请求。

    action_requests: 每份报告一个， args 为可编辑的元数据字段。
    review_configs:  每份报告允许 approve / edit / reject，并提供可编辑的字段 schema。
    """
    pending = [p for p in plans if _plan_requires_metadata_confirmation(p)]
    _METADATA_ARGS_SCHEMA = {
        "patient_code": {"type": "string", "description": "归属人编码（self/mother/father/...)"},
        "patient_name":  {"type": "string", "description": "真实姓名"},
        "report_date":   {"type": "string", "description": "报告日期 (YYYY-MM-DD)"},
        "report_type":   {"type": "string", "description": "报告类型，如血常规、CT"},
        "hospital_name": {"type": "string", "description": "医院名称"},
    }
    return HITLRequest(
        action_requests=[
            HITLActionRequest(
                name=plan["group_id"],
                description=(
                    (plan.get("prepared_report") or {}).get("report_metadata", {}).get("parse_notes")
                    or "请确认报告关键信息"
                ),
                args={
                    k: v
                    for k, v in ((plan.get("prepared_report") or {}).get("report_metadata") or {}).items()
                    if k in _METADATA_ARGS_SCHEMA
                },
            )
            for plan in pending
        ],
        review_configs=[
            HITLReviewConfig(
                action_name=plan["group_id"],
                allowed_decisions=["approve", "edit", "reject"],
                args_schema=_METADATA_ARGS_SCHEMA,
            )
            for plan in pending
        ],
    ).model_dump(exclude_none=True)


def _apply_metadata_confirmation(plans: list[dict[str, Any]], decision: Any) -> list[dict[str, Any]]:
    """decision 格式为 agent-inbox 返回的 HITLResumePayload。"""
    updated_plans = copy.deepcopy(plans)

    # 小量兼容：非字典全部确认
    if not isinstance(decision, dict):
        for plan in updated_plans:
            if _plan_requires_metadata_confirmation(plan):
                plan["metadata_confirmed"] = True
        return updated_plans

    # 尝试解析为 HITLResumePayload
    try:
        resume = HITLResumePayload.model_validate(decision)
        decisions_by_name = {d.action_name: d for d in resume.decisions if d.action_name}
    except (ValidationError, Exception):
        decisions_by_name = {}

    for plan in updated_plans:
        if not _plan_requires_metadata_confirmation(plan):
            continue
        d = decisions_by_name.get(plan["group_id"])

        # 未包含在 decision 中，默认确认
        if d is None:
            plan["metadata_confirmed"] = True
            continue

        if d.type == "reject":
            plan["selected"] = False
            plan["metadata_confirmed"] = True
            continue

        # approve 或 edit：将用户编辑的字段写回 metadata
        prepared_report = copy.deepcopy(plan.get("prepared_report") or {})
        raw_metadata = copy.deepcopy(prepared_report.get("report_metadata") or {})

        if d.type == "edit" and d.edited_action and isinstance(d.edited_action.args, dict):
            raw_metadata.update(d.edited_action.args)

        raw_metadata["parse_status"] = "parsed"
        prepared_report["report_metadata"] = ReportMetadata.model_validate(raw_metadata).model_dump(
            mode="json"
        )
        plan["prepared_report"] = prepared_report
        plan["metadata_confirmed"] = True
    return updated_plans


def _collect_plan_image_urls(plan: dict[str, Any], human_image_list: list[dict[str, Any]]) -> list[str]:
    ordered_indices = plan.get("ordered_image_indices") or plan.get("image_indices") or []
    image_urls: list[str] = []
    for image_index in ordered_indices:
        zero_based_index = image_index - 1
        if 0 <= zero_based_index < len(human_image_list):
            image_urls.append(human_image_list[zero_based_index]["image_url"]["url"])
    return image_urls


def _build_image_store_status_message(
    human_image_store_list: list[str], plans: list[dict[str, Any]]
) -> str:
    stored_images = []
    not_stored_images = []
    failed_images = []

    # 统计单张图的状态
    for index, status in enumerate(human_image_store_list, start=1):
        if status == "store_success":
            stored_images.append(index)
        elif status == "no_store":
            not_stored_images.append(index)
        elif status == "store_failed":
            failed_images.append(index)

    lines: list[str] = []

    # 1. 描述分组存储的具体情况
    successful_plans = [p for p in plans if p.get("selected") and "store_result" in p]
    if successful_plans:
        lines.append("### 报告入库详情")
        for plan in successful_plans:
            group_id = plan.get("group_id", "未知分组")
            # 优先使用有序索引，否则使用原始索引
            indices = plan.get("ordered_image_indices") or plan.get("image_indices") or []
            indices_str = " -> ".join(map(str, indices))
            report_type = plan.get("report_type") or "医疗报告"
            lines.append(f"- **{report_type} ({group_id})**: 图片顺序为 [{indices_str}]")
        lines.append("")  # 分隔符

    # 2. 总体状态汇总
    if stored_images:
        lines.append(f"✅ 系统已成功存储图片 {', '.join(map(str, stored_images))} 到您的健康档案。")
    if not_stored_images:
        lines.append(f"ℹ️ 以下图片未存储：图片 {', '.join(map(str, not_stored_images))}。")
    if failed_images:
        lines.append(f"❌ 以下图片存储失败：图片 {', '.join(map(str, failed_images))}。")

    # 3. 特殊标记（曾触发人工确认的分组）
    needs_confirm_groups = [
        plan["group_id"]
        for plan in plans
        if (plan.get("prepared_report") or {}).get("report_metadata", {}).get("parse_status") == "needs_confirm"
    ]
    if needs_confirm_groups:
        lines.append(f"\n> 注意：分组 {', '.join(needs_confirm_groups)} 曾根据您的确认调整了信息。")

    return "\n".join(lines).strip()


def _get_latest_user_question(state: AgentState) -> str:
    question_message_content = state.get("question_message_content") or []
    extracted_question = _flatten_content_to_text(question_message_content)
    if extracted_question:
        return extracted_question
    return ""


def _flatten_content_to_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        image_count = 0
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]).strip())
            elif item.get("type") in {"image", "image_url"}:
                image_count += 1
        if image_count:
            parts.append(f"用户还上传了{image_count}张图片")
        return "\n".join(part for part in parts if part)
    return str(content).strip() if content else ""

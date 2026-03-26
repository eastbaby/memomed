import copy
import json
from typing import Literal
from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field, ValidationError
from app.agent.utils.state import AgentState
from app.agent.utils.tools import get_tools
from app.agent.utils.llm import (
    get_openai_llm_non_stream,
    get_openai_llm_stream,
    get_sft_llm_non_stream,
)
from .rag import process_medical_report


class HumanImageStoreItem(BaseModel):
    """单个图片存储决策"""
    image_index: int
    store_decision: Literal["store_pending", "no_store"]


class HumanImageStoreList(BaseModel):
    """图片存储决策列表"""
    human_image_store_list: list[HumanImageStoreItem]


def process_input(state: AgentState) -> dict:
    """处理用户输入, 单独处理用户输入的图片消息
    
    Args:
        state: 当前状态
        
    Returns:
        pass
    """
    messages = state["messages"]
    question_message_content = copy.deepcopy(messages[-1]['content'])

    # step1 把messages中type: image的消息转换为type:image_url格式并存储到human_image_list中 （注意：只处理最近一次用户输入的图片消息）
    human_image_list = []
    
    for item in question_message_content:
        if isinstance(item, dict) and item.get('type') == 'image':
            item['type'] = 'image_url'
            item['image_url'] = {"url": f"data:{item['mimeType']};base64,{item['data']}"}
            del item['data']
            human_image_list.append(item)
    
    # step2 call llm 判断是否需要存储图片到数据库
    human_image_store_list = _decide_whether_store_image(question_message_content, human_image_list)


    # step3 针对需要store的数据进行rag store操作
    for i, item in enumerate(human_image_list):
        if i < len(human_image_store_list) and human_image_store_list[i] == "store_pending":
            process_medical_report(item['image_url']['url'])
            human_image_store_list[i] = "store_success"


    # step4 针对上述操作给用户反馈
    image_store_status_msg = ""
    stored_images = []
    not_stored_images = []
    for i, status in enumerate(human_image_store_list):
        if status == "store_success":
            stored_images.append(i + 1)
        elif status == "no_store":
            not_stored_images.append(i + 1)
    
    if stored_images:
        image_store_status_msg += f"系统已自动存储图片{', '.join(map(str, stored_images))}到数据库中，日后可以随时检索。\n"
    if not_stored_images:
        image_store_status_msg += f"以下图片未存储：图片{', '.join(map(str, not_stored_images))}。\n"

    return {
        "messages": [AIMessage(content=image_store_status_msg)] if image_store_status_msg else [],
        "question_message_content": question_message_content,
        "human_image_list": human_image_list,
        "human_image_store_list": human_image_store_list
    }


def _decide_whether_store_image(question_message_content: list, human_image_list: list) -> list[Literal["store_pending", "no_store"]]:
    """判断是否需要存储图片到数据库
    
    Args:
        question_message_content: 当前用户输入的内容
        human_image_list: 包含用户输入的图片消息的列表
        
    Returns:
        human_image_store_list: 包含用户输入的图片消息的列表，根据判断结果添加store_pending或no_store标签
    """
    if not human_image_list:
        return []
    
    try:
        llm = get_openai_llm_non_stream()
        
        prompt = f"""你是一个智能助手，需要判断用户上传的图片是否需要存储到向量数据库中。

        需要存储的条件：
        1. 和体检、出院小结、检验报告等所有健康报告相关的所有报告（包括但不限于：体检报告、出院小结、检验报告、血常规、尿常规、肝功能、肾功能、血糖、血脂、血压、心电图、B超、超声、CT、核磁共振、病理报告等）
        2. 用户强烈要求存储到RAG/向量数据库中

        不需要存储的条件：
        1. 日常生活照片（风景、人物、食物等与健康报告无关的照片）
        2. 无关的图片或截图

        请根据以上条件判断是否需要存储图片。按给定的human_image_list顺序返回结果。
        """
        
        structured_llm = llm.with_structured_output(HumanImageStoreList)
        
        text_content = [item for item in question_message_content if isinstance(item, dict) and item.get('type') == 'text']
        new_content = text_content + human_image_list
        
        system_message = {"role": "system", "content": prompt}
        user_message = {"role": "user", "content": new_content}
        response = structured_llm.invoke([system_message, user_message])
        
        return [item.store_decision for item in response.human_image_store_list]
    except Exception as e:
        raise ValueError(f"分析图片失败，{str(e)}")



def call_model(state: AgentState) -> dict:
    """调用语言模型
    
    Args:
        state: 当前状态
        
    Returns:
        状态更新
    """
    llm = get_openai_llm_stream()
    tools = get_tools()
    answer_keypoints = state.get("answer_keypoints") or _extract_answer_keypoints(state)
    answer_keypoints_text = "；".join(answer_keypoints) if answer_keypoints else "无"
    
    # 添加系统提示
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

    # 添加系统消息和图片存储状态
    system_message = {"role": "system", "content": system_prompt}
    
    # 状态更新，修改messages列表中的所有type: image的消息为type:image_url。
    # 仅针对大模型的参数format，不改变原messages内容（为了不影响前端格式的展示）
    messages = state["messages"]
    messages_copy = copy.deepcopy(messages)
    

    for msg in messages_copy:
        if 'content' in msg and isinstance(msg['content'], list):
            for item in msg['content']:
                if isinstance(item, dict) and item.get('type') == 'image':
                    item['type'] = 'image_url'
                    item['image_url'] = {"url": f"data:{item['mimeType']};base64,{item['data']}"}
                    del item['data']
    
    llm_with_tools = llm.bind_tools(tools)
    response = llm_with_tools.invoke([system_message] + messages_copy)
    return {
        "messages": [response],
        "response": response.content,
        "answer_keypoints": answer_keypoints,
    }


class MedicalAgentTask(BaseModel):
    """医疗助手Agent任务编排输出格式（SFT 输出结构）"""

    answer_keypoints: list[str] = Field(..., description="回答关键点，给用户的回答中必须包含的内容")


def tools_condition(state: AgentState) -> str:
    """决定是否继续执行
    
    Args:
        state: 当前状态
        
    Returns:
        下一个节点的名称
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


def _extract_answer_keypoints(state: AgentState) -> list[str]:
    """使用 SFT 模型提取最终回答必须覆盖的关键点"""
    question = _get_latest_user_question(state)
    if not question:
        return []

    llm = get_sft_llm_non_stream()
    response = llm.invoke(
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
    """生成最终响应
    
    Args:
        state: 当前状态
        
    Returns:
        状态更新
    """
    messages = state["messages"]
    last_message = messages[-1]

    return {
        "response": last_message.content if isinstance(last_message, AIMessage) else "处理完成",
        "metadata": {"status": "completed", "answer_keypoints": state.get("answer_keypoints", [])},
    }


tool_node = ToolNode(get_tools())


def _get_latest_user_question(state: AgentState) -> str:
    question_message_content = state.get("question_message_content") or []
    extracted_question = _flatten_content_to_text(question_message_content)
    if extracted_question:
        return extracted_question

    # for message in reversed(state["messages"]):
    #     if isinstance(message, HumanMessage):
    #         return _flatten_content_to_text(message.content)
    #     if isinstance(message, dict) and message.get("role") == "user":
    #         return _flatten_content_to_text(message.get("content"))
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

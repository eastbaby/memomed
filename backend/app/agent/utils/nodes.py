from langchain_core.messages import RemoveMessage, AIMessage
from langgraph.prebuilt import ToolNode
from app.agent.utils.state import AgentState
from app.agent.utils.tools import get_tools
from app.agent.utils.llm import get_llm


def process_input(state: AgentState) -> dict:
    """处理用户输入
    
    Args:
        state: 当前状态
        
    Returns:
        pass
    """
    messages = state["messages"]

    # return {"messages": messages}


def call_model(state: AgentState) -> dict:
    """调用语言模型
    
    Args:
        state: 当前状态
        
    Returns:
        状态更新
    """
    llm = get_llm()
    tools = get_tools()
    llm_with_tools = llm.bind_tools(tools)

    # 状态更新，修改messages列表中的所有type: image的消息为type:image_url。
    # 仅针对大模型的参数format，不改变原messages内容（为了不影响前端格式的展示）
    messages = state["messages"]
    messages_copy = messages.copy()

    for msg in messages_copy:
        if 'content' in msg and isinstance(msg['content'], list):
            for item in msg['content']:
                if isinstance(item, dict) and item.get('type') == 'image':
                    item['type'] = 'image_url'
                    item['image_url'] = {"url": f"data:{item['mimeType']};base64,{item['data']}"}
                    del item['data']
    
    response = llm_with_tools.invoke(messages_copy)
    return {
        "messages": [response],
        "response": response.content
    }


def should_continue(state: AgentState) -> str:
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


def generate_response(state: AgentState) -> dict:
    """生成最终响应
    
    Args:
        state: 当前状态
        
    Returns:
        状态更新
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    if isinstance(last_message, AIMessage):
        return {
            "response": last_message.content,
            "metadata": {"status": "completed"}
        }
    return {
        "response": "处理完成",
        "metadata": {"status": "completed"}
    }


tool_node = ToolNode(get_tools())
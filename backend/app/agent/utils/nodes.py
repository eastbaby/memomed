from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from app.agent.utils.state import AgentState
from app.agent.utils.tools import get_tools
from app.settings import settings


def process_input(state: AgentState) -> dict:
    """处理用户输入
    
    Args:
        state: 当前状态
        
    Returns:
        状态更新
    """
    return {
        "user_input": state.get("user_input", ""),
        "messages": [HumanMessage(content=state.get("user_input", ""))]
    }


def call_model(state: AgentState) -> dict:
    """调用语言模型
    
    Args:
        state: 当前状态
        
    Returns:
        状态更新
    """
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        max_tokens=1000,
        streaming=True,
        extra_body={
            "enable_thinking": False  # 开启思考模式（False为关闭）
        }
    )
    tools = get_tools()
    llm_with_tools = llm.bind_tools(tools)
    
    response = llm_with_tools.invoke(state["messages"])
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
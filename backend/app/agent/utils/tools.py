from langchain_core.tools import tool


@tool
def search_web(query: str) -> str:
    """搜索网络信息
    
    Args:
        query: 搜索查询字符串
        
    Returns:
        搜索结果字符串
    """
    return f"搜索结果: {query}"


@tool
def get_current_time() -> str:
    """获取当前时间
    
    Returns:
        当前时间字符串
    """
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def calculate(expression: str) -> str:
    """计算数学表达式
    
    Args:
        expression: 数学表达式字符串，如 "2 + 2"
        
    Returns:
        计算结果字符串
    """
    try:
        result = eval(expression)
        return f"计算结果: {result}"
    except Exception as e:
        return f"计算错误: {str(e)}"


def get_tools():
    """获取所有工具
    
    Returns:
        工具列表
    """
    return [search_web, get_current_time, calculate]
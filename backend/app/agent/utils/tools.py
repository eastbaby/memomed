from langchain_core.tools import tool
from .rag import process_medical_report, get_rag_retriever


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


@tool
def process_medical_report_tool(image_url: str) -> str:
    """处理医疗报告图片，注意得识别图片是医疗报告才调用
    
    Args:
        image_url: 医疗报告图片路径，原始的以data开头的image_url数据，不允许进行任何加工
        
    Returns:
        处理结果
    """
    result = process_medical_report(image_url)
    return f"处理结果: {result['message']}\n提取的文字: {result['extracted_text'][:500]}..."


@tool
def search_medical_reports(query: str) -> str:
    """搜索医疗报告
    
    Args:
        query: 搜索查询字符串
        
    Returns:
        搜索结果
    """
    retriever = get_rag_retriever()
    docs = retriever.invoke(query)
    results = [f"内容: {doc.page_content[:300]}... 来源: {doc.metadata.get('source')}" for doc in docs]
    return "\n\n".join(results) if results else "没有找到相关医疗报告"


def get_tools():
    """获取所有工具
    
    Returns:
        工具列表
    """
    return [search_web, get_current_time, calculate, process_medical_report_tool, search_medical_reports]
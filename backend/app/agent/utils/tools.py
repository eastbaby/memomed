from langchain_core.tools import tool

from .rag import process_medical_report, search_report_chunks


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
def process_medical_report_tool(image_url: str, patient_hint: str | None = None) -> str:
    """处理医疗报告图片，注意得识别图片是医疗报告才调用
    
    Args:
        image_url: 医疗报告图片路径，原始的以data开头的image_url数据，不允许进行任何加工
        patient_hint: 可选的归属人提示，如妈妈/爸爸/我
        
    Returns:
        处理结果
    """
    result = process_medical_report(image_url, patient_hint=patient_hint)
    return (
        f"处理结果: {result['message']}\n"
        f"归属人: {result['display_name']}({result['patient_code']})\n"
        f"页数: {result['page_count']}，切片数: {result['chunk_count']}，解析状态: {result['parse_status']}"
    )


@tool
def search_medical_reports(query: str, patient_hint: str | None = None, report_type: str | None = None) -> str:
    """搜索医疗报告
    
    Args:
        query: 搜索查询字符串
        patient_hint: 可选的归属人提示，如妈妈/爸爸/我
        report_type: 可选的报告类型过滤
        
    Returns:
        搜索结果
    """
    docs = search_report_chunks(query=query, patient_code=patient_hint, report_type=report_type)
    results = [
        (
            f"内容: {doc.page_content[:300]}...\n"
            f"报告类型: {doc.metadata.get('report_type') or '未知'}\n"
            f"页码: {doc.metadata.get('page_number')}\n"
            f"医院: {doc.metadata.get('hospital_name') or '未知'}"
        )
        for doc in docs
    ]
    return "\n\n".join(results) if results else "没有找到相关医疗报告"


def get_tools():
    """获取所有工具
    
    Returns:
        工具列表
    """
    return [get_current_time, calculate, process_medical_report_tool, search_medical_reports]

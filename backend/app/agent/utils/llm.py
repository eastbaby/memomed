from langchain_openai import ChatOpenAI
# from langchain_anthropic import ChatAnthropic
from app.settings import settings


def get_llm():
    """获取语言模型实例
    
    Returns:
        ChatOpenAI实例
    """
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        max_tokens=1000,
        streaming=True,
        extra_body={
            "enable_thinking": False  # 开启思考模式（False为关闭）
        }
    )


# def get_anthropic_llm():
#     """获取Anthropic语言模型实例
    
#     Returns:
#         ChatAnthropic实例
#     """
#     return ChatAnthropic(
#         model=settings.LLM_MODEL,
#         anthropic_api_key=settings.LLM_API_KEY,
#         anthropic_api_url=settings.LLM_BASE_URL,
#         max_tokens=1000,
#         streaming=True,
#     )

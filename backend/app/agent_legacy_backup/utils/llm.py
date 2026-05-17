from langchain_openai import ChatOpenAI
# from langchain_anthropic import ChatAnthropic
from app.settings import settings


def get_openai_llm_stream():
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

def get_openai_llm_non_stream():
    """获取语言模型实例
    
    Returns:
        ChatOpenAI实例
    """
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        max_tokens=1000,
        streaming=False,
        extra_body={
            "enable_thinking": False  # 开启思考模式（False为关闭）
        }
    )


def get_sft_llm_non_stream():
    """获取用于关键回答点抽取的 SFT 模型实例"""
    return ChatOpenAI(
        model=settings.SFT_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        max_tokens=500,
        streaming=False,
        extra_body={
            "enable_thinking": False
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

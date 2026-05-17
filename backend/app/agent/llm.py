from langchain_openai import ChatOpenAI

from app.settings import settings


def get_openai_llm_stream() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        max_tokens=1000,
        streaming=True,
        extra_body={"enable_thinking": False},
    )


def get_openai_llm_non_stream() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        max_tokens=1000,
        streaming=False,
        extra_body={"enable_thinking": False},
    )

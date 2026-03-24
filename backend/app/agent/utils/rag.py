from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_postgres import PGEngine, PGVectorStore
from app.agent.utils.llm import get_llm
from app.settings import settings

# 创建PGEngine
pg_engine = PGEngine.from_connection_string(
    url=settings.POSTGRES_URI_CUSTOM
)
# embeddings = OpenAIEmbeddings(
#     model=settings.EMBEDDING_MODEL,
#     api_key=settings.LLM_API_KEY,
#     base_url=settings.LLM_BASE_URL,
# )

embeddings = DashScopeEmbeddings(
    model=settings.EMBEDDING_MODEL, # 推荐使用 v3，性价比最高
    dashscope_api_key=settings.LLM_API_KEY,
)

# 报告向量存储
vector_store = PGVectorStore.create_sync(
    engine=pg_engine,
    table_name='report_chunks',
    embedding_service=embeddings,
    id_column='id',                # 对应你 SQL 中的 id (UUID)
    content_column='content',      # 对应你 SQL 中的 content (TEXT)
    embedding_column='embedding',  # 对应你 SQL 中的 embedding (VECTOR)
    metadata_columns=None,
)

def extract_text_from_image(image_url: str) -> str:
    """从图片中提取文字
    
    Args:
        image_url: 图片路径
        
    Returns:
        提取的文字
    """
    try:
        llm = get_llm()
        # 使用大模型提取图片文字
        # 注意：这需要模型支持图片理解能力
        response = llm.invoke([{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "请提取图片中的所有文字，保持原始格式和内容"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"{image_url}"
                    }
                }
            ]
        }])
        return response.content
    except Exception as e:
        raise ValueError(f"图片提取文字失败，{str(e)}")


def create_rag_vectorstore(docs: list):
    """创建RAG向量存储
    
    Args:
        docs: 文档列表
        
    Returns:
        向量存储
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200, add_start_index=True)
    splits = splitter.split_documents(docs)
    

    # 添加文档到向量存储
    vector_store.add_documents(splits)
    
    return vector_store


def get_rag_retriever():
    """获取RAG检索器
    
    Returns:
        检索器
    """
    
    return vector_store.as_retriever(search_kwargs={"k": 4})


def process_medical_report(image_url: str):
    """处理医疗报告图片
    
    Args:
        image_path: 图片路径
        
    Returns:
        处理结果
    """
    # 提取文字
    print(f"开始处理图片: {image_url}")
    text = extract_text_from_image(image_url)
    
    # 创建文档
    doc = Document(
        page_content=text,
        metadata={"source": image_url, "type": "medical_report"}
    )
    
    # 存储到向量库
    vectorstore = create_rag_vectorstore([doc])
    
    return {
        "status": "success",
        "extracted_text": text,
        "message": "医疗报告已成功处理并存储到RAG数据库"
    }

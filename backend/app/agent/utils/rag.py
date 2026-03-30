import asyncio
import uuid
from datetime import date
from typing import Any, Literal

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_postgres import PGVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.agent.utils.llm import get_openai_llm_non_stream
from app.db import AsyncSessionLocal, pg_engine
from app.models.models import MedicalReport, Patient
from app.settings import settings


PatientCode = Literal["self", "mother", "father", "pet", "other"]
PatientType = Literal["human", "pet"]


class ReportMetadata(BaseModel):
    patient_code: PatientCode = Field(default="other", description="报告归属人编码")
    display_name: str | None = Field(default=None, description="归属人展示名称，如妈妈、爸爸")
    patient_name: str | None = Field(default=None, description="报告中的真实姓名；如果是宠物则填写宠物名字")
    patient_type: PatientType = Field(default="human", description="成员类型")
    relation_type: PatientCode | None = Field(default=None, description="归属关系")
    report_date: date | None = Field(default=None, description="报告日期，输出 YYYY-MM-DD；无法判断时为 null")
    report_type: str | None = Field(default=None, description="报告类型，如血常规、CT、B超")
    hospital_name: str | None = Field(default=None, description="医院名称")
    title: str | None = Field(default=None, description="报告标题")
    summary: str | None = Field(default=None, description="报告摘要")
    parse_status: str = Field(default="parsed", description="parsed 或 needs_confirm")
    parse_notes: str | None = Field(default=None, description="需要人工确认时说明原因")


PATIENT_DISPLAY_NAMES = {
    "self": "我",
    "mother": "妈妈",
    "father": "爸爸",
    "pet": "宠物",
    "other": "家庭成员",
}

embeddings = DashScopeEmbeddings(
    model=settings.EMBEDDING_MODEL,
    dashscope_api_key=settings.LLM_API_KEY,
)

class _VectorStoreProvider:
    def __init__(self) -> None:
        self._store: PGVectorStore | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> PGVectorStore:
        if self._store is not None:
            return self._store

        async with self._lock:
            if self._store is None:
                self._store = await PGVectorStore.create(
                    engine=pg_engine,
                    table_name="report_chunks",
                    embedding_service=embeddings,
                    id_column="id",
                    content_column="content",
                    embedding_column="embedding",
                    metadata_columns=[
                        "report_id",
                        "patient_id",
                        "report_date",
                        "report_type",
                        "hospital_name",
                        "page_number",
                        "chunk_index",
                    ],
                    metadata_json_column="metadata",
                )
        return self._store


_vector_store_provider = _VectorStoreProvider()


async def get_vector_store() -> PGVectorStore:
    return await _vector_store_provider.get()


async def extract_text_from_image(image_url: str) -> str:
    """从图片中提取文字
    
    Args:
        image_url: 图片路径
        
    Returns:
        提取的文字
    """
    try:
        llm = get_openai_llm_non_stream()
        response = await llm.ainvoke([{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "请提取图片中的所有文字，保持原始格式和内容。注意直接输出提取后的文字内容，不要加任何说明或解释"
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


async def extract_report_pages(image_urls: str | list[str]) -> list[dict[str, Any]]:
    """提取报告每一页的 OCR 内容。"""
    urls = [image_urls] if isinstance(image_urls, str) else image_urls
    texts = await asyncio.gather(*(extract_text_from_image(image_url) for image_url in urls))
    return [
        {
            "page_number": index,
            "source_uri": image_url,
            "text": text,
        }
        for index, (image_url, text) in enumerate(zip(urls, texts, strict=True), start=1)
    ]


async def extract_report_metadata(
    ocr_pages: list[dict[str, Any]], patient_hint: str | None = None
) -> ReportMetadata:
    """从 OCR 结果里抽取报告主表所需的结构化信息。"""
    combined_text = "\n\n".join(
        f"第{page['page_number']}页:\n{page['text']}" for page in ocr_pages if page.get("text")
    )
    llm = get_openai_llm_non_stream()
    structured_llm = llm.with_structured_output(ReportMetadata)
    hint_text = patient_hint or "无"
    system_prompt = """
你是医疗报告结构化助手。请根据用户提供的多页 OCR 文本提取报告元信息。

要求：
1. patient_code 只输出 self、mother、father、pet、other 之一。
2. patient_type 只输出 human 或 pet。
3. relation_type 优先输出 self、mother、father、pet、other。
4. patient_name 尽量提取报告里的真实姓名；如果是宠物报告，填写宠物名字。
5. report_date 尽量提取报告日期，无法确认时返回 null。
6. 如果报告归属人、日期、类型等关键信息不确定，请把 parse_status 设为 needs_confirm，并在 parse_notes 中说明。
7. summary 用 1-2 句话概括即可。
8. 必须输出合法的 JSON，并严格匹配给定 schema，不要输出额外说明。
"""
    return await structured_llm.ainvoke(
        [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"用户提示的归属人线索：{hint_text}\n\nOCR内容如下：\n{combined_text}",
            },
        ]
    )


def _normalize_patient_code(patient_code: str | None) -> str:
    if not patient_code:
        return "other"
    normalized = str(patient_code).strip().lower()
    if normalized in PATIENT_DISPLAY_NAMES:
        return normalized
    return "other"



async def _aget_or_create_patient(session, metadata: ReportMetadata) -> Patient:
    patient_code = _normalize_patient_code(metadata.relation_type or metadata.patient_code)
    legal_name = metadata.patient_name.strip() if metadata.patient_name else None
    patient = None
    if legal_name:
        patient = (
            await session.execute(
                select(Patient).where(
                    or_(
                        Patient.legal_name == legal_name,
                        Patient.patient_code == patient_code,
                    )
                )
            )
        ).scalar_one_or_none()
    else:
        patient = (
            await session.execute(select(Patient).where(Patient.patient_code == patient_code))
        ).scalar_one_or_none()
    if patient:
        return patient

    patient = Patient(
        patient_code=patient_code,
        display_name=metadata.display_name or metadata.patient_name or PATIENT_DISPLAY_NAMES.get(_normalize_patient_code(metadata.relation_type or metadata.patient_code), "家庭成员"),
        legal_name=legal_name,
        patient_type=metadata.patient_type,
        relation_type=metadata.relation_type or _normalize_patient_code(metadata.patient_code),
    )
    session.add(patient)
    await session.flush()
    return patient


def _build_chunk_documents(
    report_id: uuid.UUID,
    patient_id: uuid.UUID,
    report_type: str | None,
    report_date: date | None,
    hospital_name: str | None,
    ocr_pages: list[dict[str, Any]],
) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150, add_start_index=True)
    chunk_documents: list[Document] = []
    chunk_index = 0

    for page in ocr_pages:
        page_number = page["page_number"]
        page_text = page.get("text") or ""
        page_doc = Document(page_content=page_text, metadata={"page_number": page_number})
        page_splits = splitter.split_documents([page_doc])

        for split in page_splits:
            metadata = {
                "report_id": str(report_id),
                "patient_id": str(patient_id),
                "report_date": report_date.isoformat() if report_date else None,
                "report_type": report_type,
                "hospital_name": hospital_name,
                "page_number": page_number,
                "chunk_index": chunk_index,
                "start_index": split.metadata.get("start_index"),
            }
            chunk_documents.append(Document(page_content=split.page_content, metadata=metadata))
            chunk_index += 1

    return chunk_documents


async def store_report_and_chunks(
    ocr_pages: list[dict[str, Any]],
    report_metadata: ReportMetadata,
    source_uri: str,
) -> dict[str, Any]:
    """写入报告主表和切片向量表。"""
    report_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    patient_code: str | None = None
    display_name: str | None = None
    chunk_documents: list[Document] = []

    async with AsyncSessionLocal() as session:
        try:
            patient = await _aget_or_create_patient(session, report_metadata)
            report = MedicalReport(
                patient_id=patient.id,
                source_type="image",
                source_uri=source_uri,
                report_date=report_metadata.report_date or date.today(),
                report_type=report_metadata.report_type,
                hospital_name=report_metadata.hospital_name,
                title=report_metadata.title,
                summary=report_metadata.summary,
                ocr_pages=ocr_pages,
                parse_status=report_metadata.parse_status,
                parse_notes=report_metadata.parse_notes,
                extra_metadata={
                    "patient_code": patient.patient_code,
                    "display_name": patient.display_name,
                    "page_count": len(ocr_pages),
                },
            )
            session.add(report)
            await session.flush()
            report_id = report.id
            patient_id = patient.id
            patient_code = patient.patient_code
            display_name = patient.display_name

            chunk_documents = _build_chunk_documents(
                report_id=report.id,
                patient_id=patient.id,
                report_type=report.report_type,
                report_date=report.report_date,
                hospital_name=report.hospital_name,
                ocr_pages=ocr_pages,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    try:
        vector_store = await get_vector_store()
        await vector_store.aadd_documents(
            chunk_documents,
            ids=[str(uuid.uuid4()) for _ in chunk_documents],
        )
    except Exception:
        async with AsyncSessionLocal() as session:
            try:
                if report_id:
                    stored_report = await session.get(MedicalReport, report_id)
                    if stored_report:
                        await session.delete(stored_report)
                        await session.commit()
            except Exception:
                await session.rollback()
        raise

    return {
        "report_id": str(report_id),
        "patient_id": str(patient_id),
        "patient_code": patient_code,
        "display_name": display_name,
        "page_count": len(ocr_pages),
        "chunk_count": len(chunk_documents),
        "parse_status": report_metadata.parse_status,
    }


async def get_rag_retriever(search_kwargs: dict | None = None):
    """获取默认 RAG 检索器。"""
    kwargs = {"k": 4}
    if search_kwargs:
        kwargs.update(search_kwargs)
    vector_store = await get_vector_store()
    return vector_store.as_retriever(search_kwargs=kwargs)


async def search_report_chunks(
    query: str,
    patient_code: str | None = None,
    report_type: str | None = None,
    k: int = 4,
) -> list[Document]:
    filter_dict: dict[str, Any] = {}
    async with AsyncSessionLocal() as session:
        if patient_code:
            normalized_code = _normalize_patient_code(patient_code)
            patient = (
                await session.execute(select(Patient).where(Patient.patient_code == normalized_code))
            ).scalar_one_or_none()
            if patient:
                filter_dict["patient_id"] = str(patient.id)
        if report_type:
            filter_dict["report_type"] = report_type

    vector_store = await get_vector_store()
    return await vector_store.asimilarity_search(query=query, k=k, filter=filter_dict or None)


async def process_medical_report(image_urls: str | list[str], patient_hint: str | None = None):
    """处理医疗报告图片并写入主表与向量表。"""
    ocr_pages = await extract_report_pages(image_urls)
    report_metadata = await extract_report_metadata(ocr_pages, patient_hint=patient_hint)
    source_uri = ocr_pages[0]["source_uri"] if len(ocr_pages) == 1 else "multi_image_upload"
    store_result = await store_report_and_chunks(ocr_pages, report_metadata, source_uri=source_uri)

    return {
        "status": "success",
        "report_id": store_result["report_id"],
        "patient_code": store_result["patient_code"],
        "display_name": store_result["display_name"],
        "parse_status": store_result["parse_status"],
        "page_count": store_result["page_count"],
        "chunk_count": store_result["chunk_count"],
        "ocr_pages": ocr_pages,
        "message": "医疗报告已成功处理并存储到RAG数据库",
    }

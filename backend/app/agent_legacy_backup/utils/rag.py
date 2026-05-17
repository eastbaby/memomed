import asyncio
import uuid
from datetime import date
from enum import Enum
from typing import Any

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_postgres import PGVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.agent.utils.llm import get_openai_llm_non_stream
from app.db import AsyncSessionLocal, pg_engine
from app.models.models import MedicalReport, Patient
from app.settings import settings


class PatientCode(str, Enum):
    """报告归属人编码，与 Patient.patient_code 数据库字段对应。"""
    SELF = "self"
    MOTHER = "mother"
    FATHER = "father"
    PET = "pet"
    HUSBAND = "husband"
    WIFE = "wife"
    FATHER_IN_LAW = "father_in_law"
    MOTHER_IN_LAW = "mother_in_law"
    OTHER = "other"

    @property
    def display_name(self) -> str:
        """归属人中文展示名称。"""
        _NAMES = {
            PatientCode.SELF: "我",
            PatientCode.MOTHER: "妈妈",
            PatientCode.FATHER: "爸爸",
            PatientCode.PET: "宠物",
            PatientCode.HUSBAND: "老公",
            PatientCode.WIFE: "老婆",
            PatientCode.FATHER_IN_LAW: "公公/岳父",
            PatientCode.MOTHER_IN_LAW: "婆婆/岳母",
            PatientCode.OTHER: "家庭成员",
        }
        return _NAMES[self]


class PatientType(str, Enum):
    """报告归属人类型。"""
    HUMAN = "human"
    PET = "pet"


class ReportMetadata(BaseModel):
    patient_code: PatientCode = Field(default=PatientCode.OTHER, description="报告归属人编码")
    display_name: str | None = Field(default=None, description="归属人展示名称(中文表示)，如妈妈、爸爸")
    patient_name: str | None = Field(default=None, description="报告中的真实姓名；如果是宠物则填写宠物名字")
    patient_type: PatientType = Field(default=PatientType.HUMAN, description="成员类型")
    report_date: date | None = Field(default=None, description="报告日期，输出 YYYY-MM-DD")
    report_type: str | None = Field(default=None, description="报告类型，如血常规、CT、B超")
    hospital_name: str | None = Field(default=None, description="医院名称")
    title: str | None = Field(default=None, description="报告标题")
    summary: str | None = Field(default=None, description="报告摘要。1-2 句话即可。")
    parse_status: str = Field(default="parsed", description="parsed 或 needs_confirm")
    parse_notes: str | None = Field(default=None, description="需要人工确认时说明原因")

    @field_validator("patient_type", mode="before")
    @classmethod
    def coerce_patient_type(cls, v: Any) -> str:
        """将 LLM 可能输出的非法值（如 'adult'）降级为 PatientType.HUMAN，避免 ValidationError。"""
        valid = {e.value for e in PatientType}
        return v if v in valid else PatientType.HUMAN.value

    @field_validator("patient_code", mode="before")
    @classmethod
    def coerce_patient_code(cls, v: Any) -> str:
        """将 LLM 可能输出的非法值降级为 PatientCode.OTHER，避免 ValidationError。"""
        valid = {e.value for e in PatientCode}
        return v if v in valid else PatientCode.OTHER.value

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


def _build_field_requirements(patient_codes_str: str, patient_types_str: str, current_date_str: str) -> str:
    """根据 ReportMetadata 的字段定义动态生成提取规则，避免手动维护。"""
    lines = []
    for field_name, field_info in ReportMetadata.model_fields.items():
        desc = field_info.description or ""
        if not desc:
            continue
        if field_name == "patient_code":
            lines.append(f"- patient_code：{desc}，只能输出 {patient_codes_str} 之一。优先根据对话上下文判断归属人，其次才是 OCR 内容。")
        elif field_name == "patient_type":
            lines.append(f"- patient_type：{desc}，只能输出 {patient_types_str} 之一。")
        elif field_name == "report_date":
            lines.append(f"- report_date：{desc}，参考当前日期 {current_date_str}，报告日期应在当前日期当天或之前。如果ocr和对话中没有明确日期，则返回null, 表示信息不确定")
        elif field_name == "parse_status":
            lines.append(f"- parse_status：{desc}。当归属人、日期、报告类型等关键信息不确定时，设为 needs_confirm，并在 parse_notes 中说明原因。")
        else:
            lines.append(f"- {field_name}：{desc}。")
    return "\n".join(lines)


async def extract_report_metadata(
    ocr_pages: list[dict[str, Any]],
    conversation_context: str | None = None,
) -> ReportMetadata:
    """从 OCR 结果里抽取报告主表所需的结构化信息。

    Args:
        ocr_pages: OCR 识别结果列表。
        conversation_context: 用户与助手的对话摘要，用于辅助判断报告归属人等信息。
    """
    combined_text = "\n\n".join(
        f"第{page['page_number']}页:\n{page['text']}" for page in ocr_pages if page.get("text")
    )
    llm = get_openai_llm_non_stream()
    structured_llm = llm.with_structured_output(ReportMetadata)

    patient_codes_str = "、".join(e.value for e in PatientCode)
    patient_types_str = "/".join(e.value for e in PatientType)
    current_date_str = date.today().isoformat()
    field_requirements = _build_field_requirements(patient_codes_str, patient_types_str, current_date_str)

    system_prompt = f"""
你是医疗报告结构化助手。请根据提供的对话上下文（如果有）和 OCR 文本，提取报告元信息。
当前日期：{current_date_str}。

各字段要求（尽量提取，实在无法确认的才留 null）：
{field_requirements}

输出要求：必须输出合法的 JSON，严格匹配给定 schema，不要输出额外说明。
"""

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
    ]

    if conversation_context:
        messages.append({
            "role": "user",
            "content": f"当前对话上下文（请优先参考此信息判断报告归属人）：\n{conversation_context}",
        })
        messages.append({"role": "assistant", "content": "明白，我会结合对话上下文和 OCR 内容进行分析。"})

    messages.append({
        "role": "user",
        "content": f"OCR内容如下：\n{combined_text}",
    })

    return await structured_llm.ainvoke(messages)


def _normalize_patient_code(patient_code: Any) -> str:
    """标准化归属人编码，确保返回合法的 PatientCode 枚举值字符串。"""
    if not patient_code:
        return PatientCode.OTHER.value
    if isinstance(patient_code, PatientCode):
        return patient_code.value



async def _aget_or_create_patient(session, metadata: ReportMetadata) -> Patient:
    patient_code = _normalize_patient_code(metadata.patient_code)
    patient_name = metadata.patient_name.strip() if metadata.patient_name else None
    patient = None
    if patient_name:
        patient = (
            await session.execute(
                select(Patient).where(
                    or_(
                        Patient.patient_name == patient_name,
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
        display_name=metadata.display_name or PatientCode(patient_code).display_name,
        patient_name=patient_name,
        patient_type=metadata.patient_type,
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
                report_date=report_metadata.report_date or date.today(),  # 用当前日期兜底
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


async def process_medical_report(image_urls: str | list[str]):
    """处理医疗报告图片并写入主表与向量表。"""
    prepared_report = await prepare_medical_report(image_urls)
    store_result = await store_prepared_medical_report(prepared_report)

    return {
        "status": "success",
        "report_id": store_result["report_id"],
        "patient_code": store_result["patient_code"],
        "display_name": store_result["display_name"],
        "parse_status": store_result["parse_status"],
        "page_count": store_result["page_count"],
        "chunk_count": store_result["chunk_count"],
        "ocr_pages": prepared_report["ocr_pages"],
        "message": "医疗报告已成功处理并存储到RAG数据库",
    }


def _build_source_uri(image_urls: str | list[str]) -> str:
    if isinstance(image_urls, str):
        return image_urls
    return image_urls[0] if len(image_urls) == 1 else "multi_image_upload"


async def prepare_medical_report(
    image_urls: str | list[str],
    conversation_context: str | None = None,
) -> dict[str, Any]:
    """预解析医疗报告，返回可序列化的 OCR 和结构化元信息。

    Args:
        image_urls: 图片 URL 列表。
        conversation_context: 历史对话摘要，用于辅助识别报告归属人。
    """
    ocr_pages = await extract_report_pages(image_urls)
    report_metadata = await extract_report_metadata(ocr_pages, conversation_context=conversation_context)
    return {
        "ocr_pages": ocr_pages,
        "report_metadata": report_metadata.model_dump(mode="json"),
        "source_uri": _build_source_uri(image_urls),
    }


async def store_prepared_medical_report(prepared_report: dict[str, Any]) -> dict[str, Any]:
    """将 prepare_medical_report 的结果正式写入数据库。"""
    ocr_pages = prepared_report["ocr_pages"]
    source_uri = prepared_report["source_uri"]
    report_metadata = ReportMetadata.model_validate(prepared_report["report_metadata"])
    return await store_report_and_chunks(ocr_pages, report_metadata, source_uri=source_uri)

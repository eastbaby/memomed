from typing import Annotated, Literal
from typing_extensions import TypedDict
import operator


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    question_message_content: list
    human_image_list: list
    human_image_store_list: list[Literal["store_success", "store_failed", "store_pending", "no_store"]]
    # 每个 dict 对应一个报告分组（由 ReportUploadGroup 序列化而来），运行时额外附加字段：
    #   selected: bool | None      — 上传决策（None=待确认 / True=已批准 / False=已拒绝）
    #   features: list[dict]       — 该组每张图的单图特征（ReportImageFeature.model_dump()）
    #   prepared_report: dict      — prepare_medical_report 的返回结果（元数据 + OCR 内容）
    #   store_result: dict         — store_prepared_medical_report 的返回结果
    #   store_error: str           — 入库失败时的错误信息
    #   metadata_confirmed: bool   — 元数据是否已经过 confirm_report_metadata 确认
    report_upload_plans: list[dict]  # LangGraph 的 checkpointer 默认用 JSON 序列化 state。list[dict] 天然兼容，list[BaseModel] 有兼容性问题。
    answer_keypoints: list[str]
    response: str
    metadata: dict

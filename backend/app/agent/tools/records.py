from langchain_core.tools import tool


@tool
async def query_health_records_tool(subject_id: str, record_type: str | None = None, limit: int = 5) -> dict:
    """查询某个家庭成员或宠物的健康报告、住院报告、体检报告或病历记录。"""
    return {
        "status": "capability_missing",
        "message": "已确认健康档案对象，但报告查询工具尚未接入。",
        "data": {
            "subject_id": subject_id,
            "record_type": record_type,
            "limit": limit,
        },
    }

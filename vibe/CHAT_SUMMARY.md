# 当前进展

## 已确认的设计
- RAG 采用双层表结构：
  - `medical_reports`：报告主表
  - `report_chunks`：切片向量表
- 高频过滤字段落列，不只放 metadata：
  - `patient_id`
  - `report_date`
  - `report_type`
  - `hospital_name`
  - `page_number`
  - `chunk_index`
- `ocr_text` 已改为 `ocr_pages JSONB`，按页保存 OCR 结果。
- `patient_code` 现在只表示类别 code：
  - `self / mother / father / pet / other`
- 具体归属主要靠：
  - `legal_name`
  - `patient_type`
  - `relation_type`


## RAG 当前实现
- `rag.py` 已重构为：
  - OCR 提取
  - 结构化 metadata 提取
  - 写 `medical_reports`
  - 切 chunk
  - 写 `report_chunks`
- 结构化提取使用 `with_structured_output(...)`，prompt 已显式要求输出 JSON，避免供应商 `json_object` 报错。
- `ReportMetadata` 中：
  - `patient_code / patient_type / relation_type` 已改为枚举约束
  - 默认值更保守，避免误判成 `self`
- `source_uri` 不再冗余存到 chunk metadata。

## 技术决策
- 数据库访问采用“方案三”：
  - 统一复用 `langchain-postgres` 的 `PGEngine._pool`
  - 业务表通过 `AsyncSession`
  - 向量表暂时继续用 `PGVectorStore`
- 注意：
  - 这并没有实现严格单事务
  - 只是统一了底层 engine 和访问风格

## 已修复的问题
- `relationship` 字段名与 SQLAlchemy `relationship()` 冲突：
  - 已改成 `relation_type`
- 结构化输出报错：
  - 已在 prompt 中加入 “必须输出合法 JSON”
- async 内部调用 sync `vector_store.add_documents()` 导致卡住：
  - 已改为 `await vector_store.aadd_documents(...)`
- `report_chunks.report_id` 外键失败：
  - 先提交 `medical_reports`
  - 再写 `report_chunks`
  - 若 chunk 写入失败，补偿删除主表记录
- `nodes.py` 中前置 `_extract_patient_hint(...)` 已删除，归属判断统一下沉到 `rag.py`

## 当前已知限制
- `parse_status = needs_confirm` 目前只会存库，还没有真正接入 `interrupt` 确认流程。
- `parse_notes` 仍可能出现 LLM 误判，后续应增加程序级校验。
- 多图上传目前还未实现“自动分组 + 页序推断 + 用户确认”。
- 用药提醒/管理功能还未开始建表和实现 tools。

## 推荐下一步
- 优先做多图报告处理：
  - 单图抽特征
  - 自动分组
  - 页序推断
  - `interrupt` 确认
- 再补 `parse_status == needs_confirm` 的流程分支。
- 之后再做用药管理表设计与工具实现。

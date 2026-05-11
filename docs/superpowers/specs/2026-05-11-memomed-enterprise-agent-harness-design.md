# Memomed 企业级 Agent Harness 设计

日期：2026-05-11

## 目标与边界

Memomed 是一个家庭健康管理 Agent 应用，目标是帮助用户管理家庭成员的医疗报告、用药提醒、复查计划和健康沟通。系统定位是健康管理助手，不做诊断、不做处方、不替代医生。

本设计优先服务“面试展示 + 真实可落地”的目标：实现按个人/小范围云端项目可完成，架构按企业级应用思路设计，面试时可延展到平台化和生产级治理。

第一版不做完整 Skill Runtime、多 Agent 协作、医生端、处方系统、复杂多租户平台、Qdrant/OpenSearch 等重型检索基础设施。它们只作为未来演进方向保留。

## 总体架构

Memomed 不应做成一个单体聊天图，而应拆为五层：

1. 产品与 API 层：聊天、上传、报告库、用药提醒、复查计划、家庭成员、待确认中心。
2. Agent Harness 层：身份、意图、上下文、安全策略、工具治理、记忆治理、追踪评测。
3. 领域 Workflow 层：由 LangGraph 编排医疗报告、RAG 问答、用药复查等高风险流程。
4. 知识与记忆层：结构化健康事实、报告原文、全文索引、向量索引、长期记忆、事件时间线。
5. 运维与评测层：trace、audit、golden set、成本延迟、失败原因、安全策略命中。

核心原则：

- Harness 负责企业级横切能力。
- LangGraph 负责需要确定性状态、暂停恢复、HITL 和可审计的领域流程。
- RAG 是知识检索方式之一，不是完整记忆系统。
- 医疗事实必须结构化、可确认、可编辑、可审计、可撤销。

## Agent Harness

Agent Harness 是一次 Agent Run 的运行时控制层，负责把用户输入转换成可控、可追踪、可恢复、可评测的执行过程。

主链路：

```text
入口事件
→ Request Normalizer
→ Identity & Scope Resolver
→ Intent Router
→ Context Builder
→ Policy Guardrail
→ Workflow Dispatcher
→ LangGraph Workflows
→ Response Composer
→ Memory Manager
→ Trace & Eval Hooks
```

模块职责：

- Request Normalizer：统一聊天、上传、定时任务、通知回调等输入，生成标准 AgentRunRequest。
- Identity & Scope Resolver：解析 user、family workspace、patient、权限范围。
- Intent Router：识别报告入库、报告问答、用药管理、复查提醒、健康咨询、设置等意图。
- Context Builder：根据意图选择结构化档案、报告元数据、RAG、长期记忆、最近对话、工具结果。
- Policy Guardrail：识别诊断、处方调整、急症、隐私、越权、证据不足、外部副作用等风险。
- Workflow Dispatcher：将请求分发给对应 LangGraph workflow。
- Response Composer：整合 workflow 结果、证据、免责声明、引用来源，生成最终答复。
- Memory Manager：管理长期记忆写入、更新、撤销、冲突检测和后台整理。
- Trace & Eval Hooks：记录意图、工具轨迹、证据、HITL、记忆变化、成本、延迟和失败原因。

## 领域 Workflows

第一版重点实现三个 LangGraph workflow。

### 医疗报告入库 Workflow

```text
上传图片/PDF
→ 判断是否医疗报告
→ 多图分组与页序判断
→ OCR / 多模态解析
→ 元数据抽取
→ HITL 确认归属人、日期、类型、医院
→ 保存原始文件和报告页
→ 生成可编辑 OCR 原文
→ 切片与索引
→ 写 health_events / audit log
```

### 医疗报告问答 Workflow

```text
问题理解
→ 解析 patient / report_type / time_range / metric
→ 结构化元数据过滤
→ 关键词检索 + 语义检索
→ RRF 融合排序 / 可选 rerank
→ evidence pack
→ 有引用回答或拒答澄清
```

### 用药复查 Workflow

```text
自然语言输入
→ 抽取药名、剂量、频率、起止时间
→ 检查缺失字段和冲突
→ HITL 确认
→ 写 medication_plan / reminder_task
→ 写 health_event / audit log
→ 后续提醒、漏服追踪、复查追踪
```

## RAG 与报告知识层

RAG 不等于记忆。Memomed 的报告知识层应采用“结构化事实 + 可编辑原文 + 全文检索 + 向量检索”的混合方案。

推荐数据模型：

```text
medical_reports
- id
- patient_id
- report_type
- report_date
- hospital_name
- title
- summary
- parse_status

report_pages
- id
- report_id
- page_number
- image_uri
- raw_text
- edited_text
- active_text
- edit_history

report_chunks
- id
- report_id
- patient_id
- page_number
- chunk_type
- chunk_text
- embedding
- search_vector
- metadata
```

检索策略：

- 患者、报告类型、日期范围先走结构化过滤。
- 报告原文用 pgvector 做语义检索。
- 指标名、药名、缩写、医生结论用 Postgres FTS 做关键词检索。
- OCR 错字、医院名、药名近似匹配可用 pg_trgm。
- 两路召回后用 RRF 融合，必要时 rerank。
- 回答必须引用 report_id、page_number、report_date、hospital_name。

技术选型：

- 个人本地版可用 SQLite + FTS5 + 可选 sqlite-vec。
- 小范围云端版推荐 Postgres + FTS + pgvector。
- 生产规模变大后，可演进到 Postgres + Qdrant + OpenSearch。

当前项目建议继续使用 Postgres + pgvector，并补齐 FTS、可编辑 OCR、重新索引和 citation。

## Memory Manager

LangGraph 的 checkpointer/store 适合作为运行时记忆基础设施，但不能替代医疗领域记忆模型。

记忆分层：

- Profile Memory：家庭成员、慢病史、过敏史、长期用药。高风险，必须确认。
- Preference Memory：沟通风格、提醒强度、称呼习惯。低风险，可自动或半自动写入。
- Episodic Memory：报告上传、就诊、用药变更、复查完成等事件时间线。
- Semantic Memory：跨多次报告和对话沉淀出的稳定总结，必须保留来源和置信度。
- Task Memory：用药计划、复查任务、提醒任务，是结构化业务状态，不是普通文本记忆。

写入策略：

- Auto-write：低风险偏好，如“回答简短一点”。
- Confirm-write：医疗事实，如长期用药、过敏史、复查计划。
- Never-write without explicit consent：敏感隐私、高风险医疗判断。

实现建议：

- LangGraph checkpointer：保存短期对话状态、HITL 暂停恢复、中间结果。
- LangGraph Store：保存低风险偏好和轻量长期记忆。
- 自建业务表：保存医疗事实、报告、任务、事件、审计。
- 后台 memory consolidation：对会话做异步总结、去重、冲突检测，不阻塞主回答。

外部 memory provider：

- 第一版不把核心医疗事实交给 Honcho/Mem0。
- 可选将 Mem0 或 Honcho 接在 Preference/User Modeling Provider 层。
- Honcho 更适合长期陪伴和用户画像；Mem0 更适合通用 memory infrastructure。

## Tool Registry 与 MCP

Tool Registry 是工具治理层，不是简单工具数组。每个工具需要定义：

```text
tool_name
description
input_schema
output_schema
risk_level
read_or_write
allowed_intents
required_scopes
requires_hitl
audit_required
timeout
retry_policy
provider
```

工具分组：

- Internal Typed APIs：写用药计划、复查任务、确认报告元数据。
- MCP Tools：只读 PostgreSQL MCP，用于查询结构化健康档案。
- Retrieval Tools：关键词检索、向量检索、hybrid retrieval。
- External Services：通知服务、日历服务。

原则：

- MCP 是 Tool Registry 下的一类 provider，不是主架构核心。
- PostgreSQL MCP 只用于只读查询和面试展示。
- 写操作必须走内部 typed API，经过业务校验、HITL 和 audit log。
- 每次工具调用前检查用户权限、patient scope、intent、风险等级、HITL 要求。

## HITL 与安全策略

执行等级：

- 自动执行：低风险、只读、无副作用，如查询报告、读取提醒计划。
- 确认后执行：医疗事实写入、任务创建、通知发送、报告归属确认。
- 拒绝或升级：诊断、处方调整、急症、危险用药建议、隐私越权。

必须 HITL 的场景：

- 报告归属人、日期、类型、页序不确定。
- 新增或修改用药计划、复查计划、提醒任务。
- 写入长期医疗事实，如过敏史、慢病史、长期用药。
- 对外发送通知、同步日历、导出隐私数据。

风险标签：

```text
medical_diagnosis
prescription_change
emergency_symptom
privacy_sensitive
family_scope_ambiguity
low_confidence_evidence
external_side_effect
```

动作：

```text
allow
allow_with_disclaimer
ask_clarification
require_hitl
refuse
escalate_to_doctor
```

所有 HITL 决策写入 human_review_tasks 和 audit log。

## Review Inbox 与前端产品形态

前端不应只有 Chat。Memomed 需要 Chat + Health Workspace。

左侧导航：

```text
Agent 对话
报告库
用药提醒
复查计划
家庭成员
待确认
```

报告库：

- 支持按家庭成员、报告类型、时间、医院、状态筛选。
- 报告详情包含概览、原文/OCR、结构化指标、引用切片、事件时间线。
- OCR 编辑采用左右布局：左侧原始图片/PDF，右侧 OCR 文本编辑器。
- 保存 edited_text 后更新 active_text，并触发 chunk rebuild、FTS reindex、embedding reindex。

Review Inbox：

- Chat 内联 Review：当前 run 的即时确认卡片，用于 resume graph。
- 全局 Review Inbox：跨会话、跨任务的 human decision queue。

底层统一使用 human_review_tasks：

```text
id
run_id
thread_id
review_type
patient_id
source_entity_type
source_entity_id
proposed_payload
status
decision
created_at
resolved_at
```

这样用户可以在 Chat 中即时确认，也可以离开对话后从待确认中心继续处理。

## Observability 与 Eval

每次 Agent Run 生成 run_id，并记录：

```text
thread_id
user_id
patient_id
intent
risk_tags
selected_workflow
model_name
prompt_version
tool_calls
retrieved_evidence
hitl_decisions
memory_changes
latency_ms
token_usage
cost
final_status
error_type
```

评测分层：

- RAG Eval：retrieval_hit_rate、metadata_filter_accuracy、citation_accuracy、answer_faithfulness、abstention_quality、latency_cost。
- Tool Trajectory Eval：是否调用正确工具、是否越权、写操作前是否 HITL、是否调用无关工具。
- Memory Eval：memory_write_precision、memory_recall_relevance、memory_conflict_detection、memory_deletion_correctness。
- Safety Eval：急症升级、处方调整拒绝、用药计划确认、证据不足澄清、隐私越权阻止。

第一版准备 30-50 条 golden set，覆盖患者混淆、报告问答、无证据拒答、用药提醒、高风险请求、memory 写入/召回。

## 部署 Profile

### Local Profile

适合个人自用、local-first 和快速演示：

```text
Runtime：LangGraph dev / FastAPI
DB：SQLite
全文检索：SQLite FTS5
向量检索：可选 sqlite-vec / LanceDB
文件：本地文件系统
任务调度：APScheduler / cron
Trace：LangSmith dev tracing
```

### Small Cloud Profile

适合给朋友使用、小范围云端部署，也是当前推荐实现目标：

```text
Runtime：FastAPI + LangGraph server
DB：Postgres
全文检索：Postgres FTS / pg_trgm
向量检索：pgvector
文件：S3 / OSS / MinIO
缓存/队列：Redis
异步任务：Celery / Dramatiq / RQ
定时任务：Celery Beat / APScheduler
Trace：LangSmith + structured logs
部署：Docker Compose / Railway / Fly.io / ECS
```

### Production Profile

适合真正产品化后演进：

```text
Runtime：Kubernetes / serverless workers
DB：Postgres / RDS
向量检索：Qdrant / Milvus
全文检索：OpenSearch / Elasticsearch
对象存储：S3 / OSS
消息队列：Kafka / RabbitMQ / SQS
任务调度：Temporal / managed scheduler
可观测性：OpenTelemetry + LangSmith + Prometheus/Grafana
安全：KMS、PII 脱敏、RLS、多租户隔离、审计平台
```

当前项目建议优先落到 Small Cloud Profile。Postgres 相比 SQLite 更适合多人云端、权限隔离、备份恢复、后台任务、并发和审计；SQLite 保留为未来 local-first profile。

## 落地顺序

1. 建立 Harness 骨架：AgentRunRequest、IdentityScope、IntentRouter、ContextBuilder、PolicyGuardrail、WorkflowDispatcher、ToolRegistry、MemoryManager、TraceLogger。
2. 升级报告知识层：report_pages、raw_text/edited_text/active_text、edit_history、FTS、pgvector、citation、重新索引。
3. 升级 Memory Manager：分层记忆、确认写入、后台整理、冲突检测、撤销。
4. 实现用药复查 Workflow：抽取、补槽、HITL、写计划、提醒、事件时间线。
5. 接入 Tool Registry + PostgreSQL MCP：只读查询展示，写操作继续走内部 API。
6. 建立 Eval：30-50 条 golden set，覆盖 RAG、tool trajectory、memory、safety。
7. 前端补齐 Health Workspace：报告库、OCR 编辑、待确认中心、用药复查管理。

## 面试总表达

Memomed 的设计不是一个聊天 demo，而是一个受约束的家庭健康管理 Agent 系统。Harness 统一处理身份、意图、上下文、安全、工具、记忆和评测；LangGraph 负责医疗报告和用药复查等需要确定性状态和 HITL 的工作流；Postgres 统一管理结构化事实、可编辑报告原文、全文检索、向量检索、任务和审计。RAG 只负责非结构化报告检索，医疗事实必须结构化、可确认、可审计。MCP 作为 Tool Registry 的只读外部工具接入，用于展示标准化工具能力，但写操作必须走内部 API、HITL 和 audit log。

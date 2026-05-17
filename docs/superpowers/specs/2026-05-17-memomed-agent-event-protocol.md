# Memomed Agent Event Protocol 与历史会话技术设计

日期：2026-05-17

## 背景

当前 Memomed 已经跑通了最小 Agent Loop：

```text
用户输入
→ LLM 判断是否调用工具
→ Tool 执行
→ Tool 可能触发 HITL
→ 用户选择/输入后继续
→ LLM 生成最终回复
```

但实际测试中暴露了几个产品级问题：

- 前端过程消息是普通 HTTP 返回后 append，容易把上一轮已有过程重复追加出来。
- Agent 过程和最终回答没有稳定的事件 ID，前端无法准确去重、更新、折叠展示。
- 当前会话没有产品层历史记录模型，刷新页面或重新进入时无法恢复完整聊天时间线。
- LangGraph checkpoint 可以恢复执行状态，但不适合直接作为产品聊天历史的唯一事实源。
- 错误、用户确认、工具结果等中间过程需要像 Codex 一样可见、可折叠、可追踪，而不是只在最终回答里体现。

因此需要定义一套 Memomed 自己的 Agent Event Protocol，把“LangGraph 执行状态”和“用户看到的聊天事件流”分清楚。

## 目标

第一阶段目标：

- 建立标准的 `conversation_id / run_id / event_id / seq` 概念。
- 支持历史会话展示和继续上次会话。
- 支持 Agent 过程折叠展示，过程事件不重复、不丢失、不含糊。
- 支持 HITL interrupt，包括选择题、确认、文本输入、未来的报告 OCR 审核。
- 后端可以从普通 HTTP 过渡到 SSE streaming，不推翻协议。
- LangGraph 使用官方 persistence/checkpointer 负责执行恢复，Memomed 自建事件表负责产品历史。

非目标：

- 第一阶段不做复杂多 Agent 分支会话。
- 第一阶段不把 LangGraph checkpoint 直接暴露给前端。
- 第一阶段不做完整审计系统，但事件模型要为审计预留字段。

## 核心结论

Memomed 第一版建议：

```text
conversation_id == LangGraph thread_id
```

也就是说，一个前端聊天会话对应一个 LangGraph checkpoint thread。

但概念上仍然要区分：

| 概念 | 所属层 | 作用 |
| --- | --- | --- |
| `conversation_id` | Memomed 产品层 | 用户看到的一段聊天会话，用于历史列表、标题、归档、权限控制。 |
| `thread_id` | LangGraph 执行层 | LangGraph checkpoint 命名空间，用于恢复 graph state、HITL interrupt、time travel。 |
| `run_id` | Memomed + LangGraph 调用层 | 一次用户输入或一次 resume 触发的执行过程。 |
| `turn_id` | Memomed 产品层 | 一次用户原始任务，可跨多次 interrupt/resume。 |
| `work_item_id` | Memomed 展示层 | 一个可折叠的 Agent 工作单元，类似 Codex 的 typed item。 |
| `work_item_type` | Memomed 展示层 | 工作单元类型，例如 `subject_resolution`、`report_ingestion`、`evidence_retrieval`。 |
| `event_id` | Memomed 事件层 | 前端去重、更新、折叠展示的稳定事件 ID。 |
| `seq` | Memomed 事件层 | 同一 conversation 内事件顺序，保证重放顺序稳定。 |

当前阶段可以让：

```text
thread_id = conversation_id
```

未来如果一个产品会话里拆出多个独立 graph，例如聊天 graph 和后台报告入库 graph，再引入：

```text
conversation_id = conv_001
thread_id = conv_001_chat
thread_id = conv_001_report_ingestion_001
```

## 为什么不能只依赖 LangGraph Checkpoint

LangGraph checkpoint 的职责是保存 graph state，例如：

- `messages`
- 当前 node
- pending interrupt
- 工具调用结果
- graph 中间状态

它非常适合做：

- 中断恢复。
- 短期上下文记忆。
- time travel 调试。
- 故障后继续执行。

但产品聊天 UI 还需要：

- 会话标题。
- 用户看到的最终消息。
- 可折叠的过程卡片。
- 每个事件的展示状态。
- 错误事件和后续用户输入事件的连续展示。
- 历史列表分页。
- 前端刷新后稳定重放。
- 未来多端同步。

这些不应该强行从 checkpoint 里解析出来。因此建议：

```text
LangGraph Checkpointer = 执行状态事实源
Memomed Event Store = 产品时间线事实源
```

## 总体架构

```mermaid
flowchart TD
    U["用户 / 前端"] --> API["Memomed API"]
    API --> ES["Memomed Event Store<br/>mm_agent_* 表"]
    API --> LG["LangGraph Runtime"]
    LG --> CP["LangGraph Checkpointer<br/>PostgresSaver"]
    LG --> TOOLS["Tools / HITL / DB"]
    TOOLS --> LG
    LG --> API
    API --> U

    ES --> HIST["历史会话回放"]
    CP --> RESUME["Graph 中断恢复"]
```

关键原则：

- 前端只消费 Memomed Event Protocol，不直接消费 LangGraph checkpoint。
- LangGraph 的 `thread_id` 使用 `conversation_id`。
- 每次用户发送消息或完成 interrupt 都创建一个新的 `run_id`。
- `run_id` 是执行边界，`work_item_id` 是 UI 折叠边界。
- 一个 `work_item_id` 可以跨多个 `run_id`，例如“确认健康档案对象”会跨用户选择前后的两次执行。
- 后端把 LangGraph streaming chunk 转换成 Memomed 标准事件。
- 前端按 `event_id` upsert，按 `seq` 排序，不按纯文本 append。
- 前端按 `work_item_id` 聚合过程卡片，而不是按 tool 或 run 聚合。

## 数据模型建议

### `mm_agent_conversations`

产品会话表。

```text
id UUID primary key
owner_user_id varchar(64) not null default 'default'
title varchar(200) nullable
status varchar(20) not null default 'active'
langgraph_thread_id varchar(100) not null
last_event_seq bigint not null default 0
created_at timestamptz not null
updated_at timestamptz not null
archived_at timestamptz nullable
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `id` | Memomed 产品会话 ID。第一版也作为 LangGraph `thread_id` 使用。 |
| `owner_user_id` | 会话所属用户。第一版固定 `default`，未来支持多账号。 |
| `title` | 会话标题，可由首条用户消息或 LLM 总结生成。 |
| `status` | `active` / `archived`。 |
| `langgraph_thread_id` | 实际传给 LangGraph config 的 `thread_id`。第一版等于 `id`。 |
| `last_event_seq` | 当前会话最后一个事件序号，用于生成下一个 `seq`。 |
| `created_at` | 创建时间。 |
| `updated_at` | 最近更新时间。 |
| `archived_at` | 归档时间。 |

### `mm_agent_runs`

一次执行表。用户发送一条消息、用户点击一个确认按钮、用户输入一个 HITL 文本，都应该生成一个 run。

```text
id UUID primary key
conversation_id UUID not null references mm_agent_conversations(id)
owner_user_id varchar(64) not null default 'default'
trigger_type varchar(30) not null
status varchar(30) not null default 'running'
langgraph_run_id varchar(100) nullable
started_at timestamptz not null
ended_at timestamptz nullable
error text nullable
metadata jsonb not null default '{}'
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `id` | Memomed run ID。 |
| `conversation_id` | 所属产品会话。 |
| `owner_user_id` | 所属用户。 |
| `trigger_type` | `user_message` / `resume_interrupt` / `background_job`。 |
| `status` | `running` / `completed` / `interrupted` / `failed` / `cancelled`。 |
| `langgraph_run_id` | 如果接入 LangGraph Server/CLI 或自定义 run tracing，可存外部 run ID。 |
| `started_at` | 执行开始时间。 |
| `ended_at` | 执行结束时间。 |
| `error` | 失败原因。 |
| `metadata` | 模型、图版本、LangSmith trace 链接等扩展信息。 |

### `mm_agent_events`

产品事件表。前端历史和实时展示都以这张表为准。

```text
id UUID primary key
conversation_id UUID not null references mm_agent_conversations(id)
run_id UUID nullable references mm_agent_runs(id)
owner_user_id varchar(64) not null default 'default'
turn_id varchar(100) nullable
work_item_id varchar(100) nullable
work_item_type varchar(60) nullable
seq bigint not null
event_type varchar(40) not null
role varchar(20) nullable
visibility varchar(20) not null default 'visible'
status varchar(20) not null default 'completed'
parent_event_id UUID nullable
dedupe_key varchar(200) nullable
title varchar(200) nullable
content text nullable
payload jsonb not null default '{}'
created_at timestamptz not null
updated_at timestamptz not null
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `id` | 稳定事件 ID，前端用它 upsert。 |
| `conversation_id` | 所属会话。 |
| `run_id` | 哪次执行产生的事件。历史导入或系统事件可为空。 |
| `owner_user_id` | 所属用户。 |
| `turn_id` | 所属用户任务。第一版可为空或由 runtime 生成，后续用于串起一次用户原始请求。 |
| `work_item_id` | 所属可折叠工作单元。前端按它聚合 Agent 过程卡片。 |
| `work_item_type` | 工作单元类型，例如 `subject_resolution`、`report_ingestion`、`health_answering`。 |
| `seq` | 会话内严格递增序号，前端按它排序。 |
| `event_type` | 事件类型，见下文。 |
| `role` | `user` / `assistant` / `tool` / `system`。 |
| `visibility` | `visible` / `collapsed` / `debug` / `hidden`。 |
| `status` | `pending` / `streaming` / `completed` / `failed`。 |
| `parent_event_id` | 子事件所属父事件，例如多个 tool step 归到一个 Agent 过程卡片下。 |
| `dedupe_key` | 同一 run 内幂等去重 key，例如 `thinking:resolve_subject:start`。 |
| `title` | 前端展示标题。 |
| `content` | 前端展示正文。 |
| `payload` | 结构化数据，例如 tool name、interrupt options、错误 code。 |
| `created_at` | 创建时间。 |
| `updated_at` | 最近更新时间。 |

建议唯一约束：

```text
unique(conversation_id, seq)
unique(run_id, dedupe_key) where dedupe_key is not null
```

## Work Item 设计

参考 Codex 的交互思想，Memomed 的折叠块不应该按 tool 粒度，也不应该简单按 turn 粒度，而应该按“用户可理解的 typed work item”聚合。

```text
conversation_id：整段聊天
turn_id：用户一次原始任务
run_id：一次后端执行，包括 interrupt resume
work_item_id：一个可折叠 Agent 工作单元
work_item_type：工作单元类型
event_id：具体事件
```

`run_id` 是执行边界，`work_item_id` 是展示边界。

例如用户说：

```text
帮我存最近报告
```

可能对应：

```text
work_item: subject_resolution / 确认健康档案对象
- resolve_patient_tool
- interrupt.requested
- 用户选择爸爸
- commit_patient_selection

work_item: report_ingestion / 处理报告文件
- 接收文件
- OCR
- 提取结构化字段

work_item: user_review / 入库前审核
- 展示草稿
- 等待用户确认
- 写库
```

一个 work item 可以包含多个 tool，也可以跨多个 run：

```text
Run 1：识别对象不确定，发出 interrupt.requested
Run 2：用户选择后 resume，确认对象成功

这两个 run 都属于同一个 work_item_id = subject_resolution_xxx
```

第一版先落地以下类型：

| work_item_type | 展示标题 | 说明 |
| --- | --- | --- |
| `subject_resolution` | 确认健康档案对象 | 识别本轮要管理的人或宠物，可跨选择/输入 interrupt。 |
| `report_ingestion` | 处理报告文件 | 后续上传、OCR、报告抽取会用。 |
| `user_review` | 等待用户审核 | 后续 OCR/入库前确认会用。 |
| `evidence_retrieval` | 检索健康资料 | 后续问答检索报告、用药、提醒时使用。 |
| `general_tool_work` | Agent 过程 | 暂时无法归类的工具工作。 |

## Event Type 设计

第一版事件类型建议保持少而稳定。

| event_type | 用途 | 前端展示 |
| --- | --- | --- |
| `message.user` | 用户消息 | 普通用户气泡 |
| `message.assistant.delta` | 助手回复增量 | 流式更新助手气泡 |
| `message.assistant.completed` | 助手最终回复完成 | 固化助手气泡 |
| `process.group.started` | Agent 过程组开始 | 创建折叠过程卡片 |
| `process.step` | 思考、计划、状态说明 | 放入过程卡片，默认折叠 |
| `tool.call.started` | 工具调用开始 | 过程卡片内部 |
| `tool.call.completed` | 工具调用成功 | 过程卡片内部 |
| `tool.call.failed` | 工具调用失败 | 过程卡片内部，红色提示 |
| `interrupt.requested` | 需要用户选择/确认/输入 | 显示交互卡片 |
| `interrupt.resumed` | 用户已完成 interrupt | 过程卡片内部 |
| `run.completed` | 本次 run 结束 | 通常不单独展示 |
| `run.failed` | 本次 run 失败 | 错误提示 |

第一版不建议让工具自由输出任意 UI 文案。工具应该输出结构化结果，runtime 再映射成标准事件。

## 事件 Payload 示例

### 用户消息

```json
{
  "id": "evt_001",
  "conversation_id": "conv_001",
  "run_id": "run_001",
  "seq": 1,
  "event_type": "message.user",
  "role": "user",
  "visibility": "visible",
  "status": "completed",
  "content": "帮我爷爷存一下报告",
  "payload": {}
}
```

### Agent 过程组

```json
{
  "id": "evt_002",
  "conversation_id": "conv_001",
  "run_id": "run_001",
  "seq": 2,
  "event_type": "process.group.started",
  "role": "assistant",
  "visibility": "collapsed",
  "status": "streaming",
  "title": "Agent 过程",
  "content": "正在确认健康档案对象",
  "payload": {
    "default_expanded": false
  }
}
```

### 工具调用

```json
{
  "id": "evt_003",
  "conversation_id": "conv_001",
  "run_id": "run_001",
  "seq": 3,
  "event_type": "tool.call.started",
  "role": "tool",
  "visibility": "collapsed",
  "parent_event_id": "evt_002",
  "title": "调用工具",
  "content": "正在识别这次要管理哪位成员或宠物",
  "payload": {
    "tool_name": "resolve_patient_tool",
    "args_summary": "用户提到了“爷爷”"
  }
}
```

### Interrupt

```json
{
  "id": "evt_004",
  "conversation_id": "conv_001",
  "run_id": "run_001",
  "seq": 4,
  "event_type": "interrupt.requested",
  "role": "assistant",
  "visibility": "visible",
  "status": "pending",
  "title": "需要确认健康档案对象",
  "content": "请选择这次要管理谁或哪只宠物的健康档案。",
  "payload": {
    "interaction": {
      "type": "select_one",
      "options": [
        {"label": "爷爷", "value": "subject_001"},
        {"label": "新建人物", "value": "create_human"}
      ]
    },
    "pending_action_id": "pa_001",
    "continuation_tool": "commit_patient_selection"
  }
}
```

### 错误后继续请求用户输入

```json
[
  {
    "event_type": "tool.call.failed",
    "content": "新建档案失败：该别名已经被其他成员或宠物使用。",
    "payload": {
      "error_code": "DUPLICATE_ALIAS",
      "tool_name": "commit_patient_selection"
    }
  },
  {
    "event_type": "interrupt.requested",
    "content": "请换一个展示名称，或去成员管理页确认已有成员。",
    "payload": {
      "interaction": {
        "type": "text_input",
        "placeholder": "例如：外公、爷爷A"
      }
    }
  }
]
```

注意：这两个事件都必须保留，不能只返回最后一个。否则前端会丢掉“为什么又让我输入”的原因。

## 前端展示规则

前端不要再简单：

```text
setProcessEvents([...old, ...new])
```

而应该使用 event reducer：

```text
收到 event
→ 如果 event_id 已存在，则更新原事件
→ 如果 event_id 不存在，则插入
→ 按 seq 排序
→ 根据 work_item_id 组织过程组
```

展示建议：

- `message.user` 显示为用户气泡。
- `message.assistant.*` 显示为助手气泡，delta 期间流式更新。
- `process.group.started` 显示为“Agent 过程”折叠卡片。
- `tool.*` 和 `process.step` 默认放在折叠卡片内部。
- 多个 `process.group.started` 如果拥有同一个 `work_item_id`，前端只展示一个折叠块。
- `tool.call.failed` 即使在折叠卡片内，也要在卡片摘要中体现。
- `interrupt.requested` 显示为显式交互卡片，不要藏在过程卡片里。
- 历史会话回放时，默认折叠过程卡片，只展示最终用户消息、助手回复和未完成 interrupt。

## 后端 API 设计

### 创建会话

```http
POST /api/agent/conversations
```

响应：

```json
{
  "conversation_id": "conv_001",
  "title": null,
  "created_at": "2026-05-17T10:00:00+08:00"
}
```

### 会话列表

```http
GET /api/agent/conversations
```

用于左侧历史列表。

### 会话事件回放

```http
GET /api/agent/conversations/{conversation_id}/events
```

支持分页：

```text
?after_seq=0&limit=100
```

响应：

```json
{
  "conversation_id": "conv_001",
  "events": [],
  "has_more": false
}
```

### 发送消息并流式执行

```http
POST /api/agent/conversations/{conversation_id}/runs/stream
```

请求：

```json
{
  "message": "帮我爷爷存一下报告",
  "attachments": []
}
```

响应建议使用 SSE：

```text
event: agent_event
data: {"id":"evt_001","event_type":"message.user",...}

event: agent_event
data: {"id":"evt_002","event_type":"process.group.started",...}

event: agent_event
data: {"id":"evt_004","event_type":"interrupt.requested",...}
```

### 恢复 interrupt

```http
POST /api/agent/conversations/{conversation_id}/runs/resume/stream
```

请求：

```json
{
  "pending_action_id": "pa_001",
  "decision": {
    "type": "select_one",
    "value": "create_human"
  }
}
```

后端使用同一个 `conversation_id` 作为 LangGraph `thread_id`，并用 `Command(resume=...)` 恢复 graph。

## LangGraph 集成方式

调用 LangGraph 时：

```python
config = {
    "configurable": {
        "thread_id": str(conversation_id)
    }
}
```

新消息：

```python
graph.astream(
    {"messages": [HumanMessage(content=user_text)]},
    config=config,
    stream_mode=["updates", "messages", "custom"],
)
```

恢复 interrupt：

```python
graph.astream(
    Command(resume=decision_payload),
    config=config,
    stream_mode=["updates", "messages", "custom"],
)
```

生产环境 checkpointer：

```text
PostgresSaver
```

本地开发可以继续使用：

```text
InMemorySaver 或 SqliteSaver
```

但只要需要页面刷新后继续 interrupt，就不能依赖 `InMemorySaver`。

## 避免重复过程消息的规则

当前重复的根因是：后端每次返回一批普通 JSON，前端直接 append；而 process event 没有稳定 ID，也没有区分“历史已有事件”和“本次新增事件”。

新协议用三层规则避免：

### 后端规则

- 每个事件生成稳定 `event_id`。
- 每个 conversation 内 `seq` 单调递增。
- 同一 run 内同一语义步骤使用 `dedupe_key`。
- 同一用户可理解工作阶段使用同一个 `work_item_id`，即使它跨了 interrupt/resume。
- API 返回“本次新产生事件”或 SSE 实时事件，不重复返回历史事件。
- 如果返回历史事件，必须通过 `GET /events` 明确回放。

### 前端规则

- 按 `event_id` upsert，不做无脑 append。
- 按 `seq` 排序。
- 按 `work_item_id` 聚合过程卡片，不按 tool 或 run 展示一堆碎片卡片。
- 同一个 `interrupt.requested` 如果还是 `pending`，只展示一张卡片。
- `status` 从 `streaming` 变成 `completed` 时更新原事件，不新增一个看起来相同的事件。

### 文案规则

- `process.step` 描述过程，避免每一步都说同一句“需要确认对象”。
- `interrupt.requested` 描述用户要做什么。
- `tool.call.completed` 描述工具做成了什么。
- 最终助手回复只面向用户总结，不重复内部过程流水账。

## 和 Codex 交互体验的对应关系

Memomed 不需要完全复制 Codex 的实现，但可以学习它的体验原则：

```text
用户消息
→ 可折叠过程
   → thinking / tool call / error / result
→ 必要时出现交互卡片
→ 用户处理交互
→ 继续过程
→ 最终回复
```

核心不是“每条过程都展示”，而是：

- 过程可追踪。
- 默认不打扰。
- 出错时可展开定位原因。
- 用户需要参与时明确打断。
- 历史回放时仍能看到当时发生了什么。

## 第一阶段落地计划

### 阶段 1：事件模型和非流式兼容

- 新建 `mm_agent_conversations`、`mm_agent_runs`、`mm_agent_events`。
- 当前 `/chat` 和 `/resume` 仍可保留普通 JSON。
- 但返回值改成标准 `events`。
- 前端改成 event reducer，通过 `event_id` 去重。
- 解决重复过程消息。

### 阶段 2：SSE streaming

- 新增 `/runs/stream` 和 `/runs/resume/stream`。
- 后端将 LangGraph stream chunk 转换成 Memomed event。
- 前端实时消费 SSE。
- 助手回复支持 delta 流式展示。

### 阶段 3：持久化恢复

- LangGraph checkpointer 从 `InMemorySaver` 升级到 `PostgresSaver`。
- 前端刷新后通过 `GET /events` 恢复时间线。
- 如果存在 pending interrupt，恢复交互卡片。

### 阶段 4：会话列表和归档

- 新增历史会话侧边栏。
- 支持会话标题生成。
- 支持归档会话。
- 支持继续上次会话。

## 推荐最终方向

Memomed 后续应采用：

```text
LangGraph = agent 执行引擎
PostgresSaver = graph state/checkpoint 持久化
mm_agent_events = 产品聊天时间线
SSE = 实时事件传输
React event reducer = 前端稳定展示
```

这个方案既保留 LangGraph 的中断恢复和状态管理能力，又避免把产品 UI 历史绑死在 LangGraph 内部 checkpoint 格式上。

第一版最重要的设计决策是：

```text
conversation_id 等于 thread_id，但不要把 conversation 和 thread 的概念混为一谈。
```

这样现在实现简单，未来扩展到后台报告 graph、分支会话、多租户时也不会推翻已有架构。

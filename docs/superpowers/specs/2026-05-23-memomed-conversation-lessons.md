# Memomed 长对话稳定经验与后续约束建议

日期：2026-05-23

## 背景

这份文档从 Memomed 近期长对话和多轮调试中提炼“稳定经验”。它不是一次性复盘，而是为了减少后续重复犯错：

- Agent Loop / HITL / Streaming 的 bug 多次重复出现。
- 有些修复偏“补丁式”，没有先定位真实原因。
- 前端实时态和历史态曾多次不一致。
- 过程事件、最终回答、工具调用、计时器这些概念容易混在一起。
- 测试一开始覆盖不够，导致用户通过手工点击不断发现问题。

这份文档后续可以拆成两类资产：

- `AGENTS.md`：放最少量、最高优先级、每次都必须遵守的工程约束。
- 项目 Skill：放更完整的工作流、排查顺序、事件协议和测试清单。

## AGENTS.md 与 Skill 的分工建议

### 适合写进 `AGENTS.md`

`AGENTS.md` 会在每次 Codex 工作时进入上下文，因此应该短、硬、稳定。适合放：

- 始终使用中文输出。
- 改 Agent / HITL / Streaming 之前，必须先读相关事件协议和质量门禁文档。
- 不允许用兜底回复掩盖 graph、LLM、tool、event 的真实错误。
- 不允许只改代码不跑测试。
- 涉及前端交互问题时，必须用 Chrome 或浏览器做真实链路验证。
- 实时流和历史回放必须表现一致。

### 不适合全写进 `AGENTS.md`

这些内容更适合留在 docs 或项目 Skill 中：

- 完整事件协议字段说明。
- LangGraph / Tool / HITL 的实现细节。
- 具体 bug 案例和历史原因分析。
- 测试矩阵。
- 前端组件结构。
- 对比 Codex 交互设计的长篇分析。

原因是：`AGENTS.md` 太长会让每次任务都带上大量不相关上下文，反而降低执行稳定性。

### 最推荐的后续形态

建议新增一个项目内 Skill，例如：

```text
.agents/skills/memomed-agent-harness/SKILL.md
```

触发场景：

- 修改 Agent Loop。
- 修改 HITL / interrupt / resume。
- 修改 SSE streaming。
- 修改 `AgentEvent` / `work_item` / `run.elapsed`。
- 修复“实时态与历史态不一致”。
- 新增 tool。

这个 Skill 应该指向本文档和以下文档：

- `docs/superpowers/specs/2026-05-17-memomed-agent-event-protocol.md`
- `docs/superpowers/specs/2026-05-18-memomed-quality-gate.md`

## 稳定经验 1：先定位真实原因，不要用 UI 去重掩盖协议问题

### 反复出现的问题

前端曾出现多个重复过程块，例如两个“确认健康档案对象”、两个“查询健康报告”。早期修复方向容易变成：

```text
同标题去重
同内容去重
同类型去重
```

这些都可能误伤，因为未来一个用户回合里确实可能出现多个同标题但不同 `work_item_id` 的工作单元。

### 稳定约束

修复重复展示前，必须先确认重复来自哪里：

- 后端是否同时发送了 streaming 过程事件和 final `result.events` 整理事件。
- 两类事件是否有不同 `work_item_id`。
- 前端是否把临时事件和最终事件都当成正式事件展示。
- 历史回放是否也重复。

### 正确方向

实时流和历史回放必须最终收敛到同一套事件语义：

- 不能简单按标题或文本去重。
- 不能跨 `work_item_id` 合并。
- 可以把临时 streaming 过程替换为最终 completed 过程，但规则必须基于协议字段。
- 最终验证要比较“实时完成后的页面”和“刷新历史后的页面”是否一致。

## 稳定经验 2：Agent 过程和最终回答是两个不同层次

### 反复出现的问题

用户看到 Agent 过程后，最终回答缺失或卡住。曾出现：

- 工具执行完就结束，没有回到 LLM 生成最终文本。
- 后端 completed 但没有 `message.assistant.completed`。
- 前端用兜底文案补一个“Agent 工具流程结束后缺少最终回复文本”。

### 稳定约束

标准路径必须是：

```text
User
→ LLM
→ Tool
→ Tool observation
→ LLM
→ message.assistant.completed
→ END
```

如果工具链完成但没有最终回答，应视为协议或 graph 错误，而不是产品兜底。

### 正确方向

- `process.step` 是过程展示，不等于最终回答。
- `ToolMessage` / tool observation 是给 LLM 继续推理的事实输入，不是直接给用户的最终输出。
- 前端可以展示过程，但一次用户请求最终必须有完整 assistant answer，除非状态明确是 `interrupted` 或 `error`。

## 稳定经验 3：HITL 等待期间仍属于同一个用户回合

### 反复出现的问题

`已处理 xxx` 计时器在 HITL 中断后停止，或用户选择后重置为 0，或最终输出时变小。

根因是混淆了三个概念：

- `run_id`：一次执行调用，用户点击确认后会产生新的 resume run。
- `turn_id`：一次用户原始任务，可能跨多次 interrupt / resume。
- 用户感知的一次等待：从用户发出请求开始，到最终完成才结束。

### 稳定约束

计时器应该按用户感知的一次 turn 计算，不应该按每个 run 单独计算。

```text
用户发消息
→ 计时开始
→ 等待 HITL 选择期间继续计时
→ resume 继续计时
→ 最终回答完成或 error 后停止
```

### 正确方向

- 前端 live timer 在 `interrupted` 状态下不能停止。
- resume 后如果已有 `runStartedAt`，不能重置。
- 后端最终 `run.elapsed` 应代表整个 user turn 的耗时。
- 实时态和历史态都只展示这一轮用户消息下的一个 `已处理 xxx`。

## 稳定经验 4：不要把某个 tool 的业务特例写进通用 system prompt

### 反复出现的问题

为了让 `resolve_patient_tool` 表现更稳定，曾倾向于在通用系统提示词里写过多成员识别规则。

这会污染未来所有 tool：

- 报告查询 tool。
- 报告入库 tool。
- 用药提醒 tool。
- 成员管理 tool。

### 稳定约束

通用 system prompt 只描述 Agent 的整体职责和通用行为边界，不写某个 tool 的细节决策。

### 正确方向

- tool 的参数 schema 描述该 tool 需要什么。
- tool 自己处理领域内输入验证。
- runtime / harness 处理通用状态和依赖注入。
- system prompt 不承担数据库约束、subject alias 规则、某个工具的 continuation 逻辑。

## 稳定经验 5：工具参数应由 LLM 负责，但 runtime 可以做通用依赖注入

### 反复出现的问题

`query_health_records_tool` 曾因为缺少 `subject_id` 触发 validation error。直接写：

```python
if capability == "health_records_query" and not subject_id:
    subject_id = current_subject
```

这种写法看起来能解决 bug，但本质是 tool 特例补丁。

### 稳定约束

不要在 runtime 里写某个 tool 名称或某个 capability 的业务分支。

### 正确方向

更通用的做法是依赖注入：

- tool spec 声明自己需要哪些上下文依赖。
- runtime 根据 spec 注入已确认的 subject、owner、conversation 等上下文。
- LLM 仍然负责根据用户意图选择 tool 和显式参数。
- 如果依赖缺失，tool 应抛出真实错误或返回明确结构化错误，不能静默猜测。

## 稳定经验 6：satisfied_capabilities 只约束同一用户 turn，不约束整个 thread

### 反复出现的问题

为避免同一轮里重复调用 `resolve_patient_tool`，曾尝试把工具从可用工具列表中移除。但用户后续可能说“换个成员”，此时仍需要重新调用同一个工具。

### 稳定约束

“能力已满足”只能按当前用户 turn 生效，不能按整个 conversation/thread 永久生效。

### 正确方向

- 同一用户请求里，已经确认过对象后，避免重复解析对象。
- 新一轮用户消息可以再次调用同一 capability。
- 用户明确要求换对象时，也应该允许再次调用 subject resolution。

## 稳定经验 7：Human interrupt 可以作为工具结果，但前端协议要独立表达

### 反复出现的问题

曾纠结 `needs_user_confirmation` 到底是 tool 的返回，还是单独节点。

稳定结论是：

- 从 Agent 内部语义看，HITL 可以是 tool 返回的一种结构化结果。
- 从前端产品协议看，必须明确转换为 `interrupt.requested` 事件。

### 稳定约束

前端不要解析 ToolMessage 来猜测是否要弹选择题。

### 正确方向

tool/runtime 可以产生：

```text
needs_user_input
needs_user_selection
needs_user_confirmation
```

但 API 层必须转成标准事件：

```text
interrupt.requested
interrupt.resumed
```

用户提交后，由 runtime 决定 continuation，而不是让前端拼 tool 调用。

## 稳定经验 8：实时流和历史回放必须用同一套 reducer

### 反复出现的问题

实时页面顺序乱，刷新后历史顺序又正常。或者实时过程重复，历史正常。

### 稳定约束

前端不能有两套时间线语义：

- 实时 SSE 一套 append 逻辑。
- 历史 API 一套排序/聚合逻辑。

### 正确方向

- 所有事件进入同一个 `mergeAgentEvents` / timeline reducer。
- 已落库事件按 `seq` 稳定排序；实时未落库事件 `seq=null`，按 `ordinal` 排序。
- `message.assistant.delta` 按 `message_id` 增量拼接。
- `message.assistant.completed` 到达后替换 streaming delta。
- `message.assistant.cancelled` 能清理工具调用前的临时助手前言。
- 历史加载也必须复用同样的 reducer。

## 稳定经验 9：过程展示应按 work item，而不是按 run 或纯文本

### 反复出现的问题

一开始把一次 `run_id` 当成一个折叠块，后来发现一次用户请求里可能有多个工具和多个阶段。又一度尝试按标题去重，导致不同工作项被挤在一起。

### 稳定约束

Agent 过程折叠块的最小单位应该是 `work_item_id`。

### 正确方向

一个用户 turn 下面可以有多个 work item：

```text
已处理 57s
确认健康档案对象
查询健康报告
报告 OCR 审核
用药提醒记录
```

每个 work item 内部有多个 step：

```text
tool.started
tool.observation
tool.error
interrupt.requested
runtime.note
```

前端可以选择展示部分 step，但底层协议必须保留清晰类型。

### 当前 `work_item_id` 的实际规则

当前代码中，过程卡片不是按标题分组，也不是按纯文本分组，而是按 `work_item_id` 分组。

`work_item_type` 决定展示标题：

```text
subject_resolution   -> 确认健康档案对象
health_records_query -> 查询健康报告
agent_progress       -> Agent 过程
```

`work_item_id` 当前由以下信息稳定生成：

```text
work_item_id = hash("wi", conversation/thread, run_id, work_item_type)
```

实时结构事件和最终 `run_result.events` 复用同一份 emitter buffer，因此不会再出现“实时按 run_id、最终按另一个 scope 重建”的差异。

因此，resume 后即使还是 `subject_resolution`，也可能因为进入了新的执行 run 而生成新的 `work_item_id`。这就是为什么同一轮用户请求中可能出现两张“确认健康档案对象”：

```text
第一张：interrupt 前，需要确认对象。
第二张：resume 后，已确认对象。
```

这不是前端随机拆分，而是后端事件协议当前的展示边界。

### 后续如果想合并同名阶段

不要在前端按标题或文案合并。正确改法是调整后端 work item scope，让 interrupt 前后的同一 pending action / user turn 使用同一个明确 scope。

注意：当前代码还没有这个跨 run scope；如果未来要做，应该先设计明确字段，而不是恢复内容 dedupe 或标题合并。

需要同时验证：

- 实时流和历史回放仍一致。
- pending interrupt 完成态仍正确。
- `interrupt.resumed` 能挂到正确的父过程组。
- 同一用户 turn 内不同工具不会被误合并。
- 新一轮用户消息仍会产生新的 work item。

## 稳定经验 10：过程文案不要假装是 chain-of-thought

### 反复出现的问题

用户希望像 Codex 一样看到丰富过程信息，但这不等于暴露模型内部 reasoning。

### 稳定约束

过程文案应该是 Agent Harness 的可观察状态，而不是模型 chain-of-thought。

### 正确方向

可以展示：

- 正在理解需求。
- 正在调用哪个工具。
- 工具返回了什么可见观察结果。
- 需要用户确认什么。
- 已处理多久。

不应该展示：

- 未经处理的模型内部思维链。
- 含糊的重复过程文案。
- 与实际执行不一致的“假进度”。

## 稳定经验 11：医疗产品宁愿明确错误，也不要静默吞错

### 反复出现的问题

曾考虑把 validation error 转成普通工具 observation，让 LLM 组织最终回复。但用户明确表示这是个人项目，希望错误尽可能抛出来。

### 稳定约束

医疗/健康数据管理场景中，错误应该可见、可追踪、可修复。

### 正确方向

- 真实参数错误不应该被“友好兜底”吞掉。
- 数据库约束错误应该明确暴露。
- UI 可以更友好地展示错误，但不能改变错误语义。
- 测试要覆盖错误路径，而不是只测 happy path。

## 稳定经验 12：主体识别必须基于数据库事实源，而不是固定选项

### 反复出现的问题

早期选项固定写死，导致成员/宠物管理不真实。后来引入 `care_subjects` / alias 后，Agent 可以从数据库查询候选对象。

### 稳定约束

成员和宠物是产品数据，不是 prompt 里的枚举。

### 正确方向

- 主体识别前先读取数据库里的 active subjects 和 aliases。
- 不确定时让用户选择。
- 用户选择新建时写入数据库。
- 成员管理页允许用户编辑、归档、修改 alias。
- alias 唯一性由数据库约束保证。

## 稳定经验 13：前端交互 bug 必须用真实浏览器验证

### 反复出现的问题

很多 bug 单测看不出来：

- 输入框位置不对。
- Chrome 正常但 Codex 内置浏览器不正常。
- 实时等待时顺序乱，刷新后正常。
- 计时器在 HITL 后表现异常。
- 折叠块交互不符合直觉。

### 稳定约束

涉及 UI/UX、SSE、HITL、历史回放时，必须至少做一次真实浏览器验证。

### 正确方向

优先使用 Chrome 插件测试用户实际打开的 `localhost:3000` 页面。验证内容至少包括：

- 发送消息。
- 等待中间过程出现。
- HITL 选择。
- 最终回复。
- 刷新后加载历史。
- 比较实时态和历史态。

## 稳定经验 14：测试用例要覆盖曾经反复出现的真实 bug，而不是只覆盖实现细节

### 反复出现的问题

用户多次指出：“为什么这个 bug 之前反馈过，又出现了？”

这说明测试没有把真实用户链路转成自动化约束。

### 稳定约束

每次修 bug 后，要补“能阻止它再次发生”的测试。

### 正确方向

优先补以下测试：

- HITL 等待时计时器继续增长。
- resume 后计时器不归零。
- 最终耗时不能比等待阶段更小。
- 实时流合并最终 result 后，展示与历史回放一致。
- 工具链完成后必须有最终 assistant answer。
- 同一 turn 内 capability 去重，但新 turn 可以重复调用。
- 同名不同 `work_item_id` 不能被错误合并。

## 稳定经验 15：文档要同步，否则后续会重复争论已定结论

### 反复出现的问题

架构多次调整后，文档没有及时同步，导致后续讨论又回到旧设计。

### 稳定约束

重大设计变化必须同步文档，尤其是：

- Agent Loop 形态。
- HITL 处理方式。
- 事件协议。
- 工具注册和依赖注入。
- 前端时间线语义。
- 测试门禁。

### 正确方向

每次完成一个稳定设计后，至少更新：

- 设计文档。
- 测试矩阵。
- 如果属于长期工作流，再考虑沉淀为项目 Skill。

## 建议写入 AGENTS.md 的精简版本

如果后续确认，可以把以下内容追加到 `AGENTS.md`：

```text
涉及 Memomed Agent / HITL / SSE / 事件协议修改时：
- 先阅读 docs/superpowers/specs/2026-05-17-memomed-agent-event-protocol.md 和 docs/superpowers/specs/2026-05-18-memomed-quality-gate.md。
- 不允许用兜底回复掩盖 graph、LLM、tool、event 的真实错误。
- 不允许把单个 tool 的业务特例写进通用 system prompt 或 runtime。
- 实时流和历史回放必须使用同一套事件语义，表现必须一致。
- 过程展示按 work_item_id 聚合，不按标题、文本或 run_id 粗暴合并。
- HITL 等待期间仍属于同一个用户 turn，计时器必须持续到最终 completed/error。
- 改 UI / streaming / HITL 后必须用真实浏览器验证关键链路。
- 提交前运行 bash scripts/quality-check.sh。
```

## 建议沉淀为 Skill 的核心规则

如果要做项目 Skill，`SKILL.md` 可以更短，只保留执行流程：

```text
当修改 Memomed Agent Harness 时：
1. 先判断是否涉及 Agent Loop、Tool、HITL、SSE、Event Store、Timeline。
2. 阅读事件协议和质量门禁文档。
3. 先复现问题，明确是后端协议、前端 reducer、还是 UI 展示问题。
4. 不用兜底回复或文本去重掩盖协议问题。
5. 修改前补能失败的测试；修改后跑质量门禁。
6. 涉及浏览器交互时，用 Chrome 验证实时态与历史态一致。
7. 最后同步相关文档。
```

## 当前优先级建议

短期建议：

1. 先保留本文档作为经验库。
2. 把“建议写入 AGENTS.md 的精简版本”拿给用户确认。
3. 用户确认后再更新 `AGENTS.md`，不要一次塞入过长内容。

中期建议：

1. 创建 `.agents/skills/memomed-agent-harness/SKILL.md`。
2. Skill 内只放短流程，详细内容链接到本文档。
3. 后续每次 Agent/HITL/Streaming 任务自动触发该 Skill。

长期建议：

1. 每次重大 bug 修复都追加“稳定经验”。
2. 每次重复 bug 都检查是否缺测试。
3. 每次设计变更都同步文档和 Skill。

# Memomed 测试用例矩阵与质量评分标准

日期：2026-05-18

## 目标

这份文档用来约束后续每次改代码时的验收标准，减少靠人工点击页面发现问题的成本。

核心原则：

- 所有 bug 修复都必须先有能复现问题的自动化测试。
- 所有 agent loop / HITL / 事件协议改动，都必须跑完整质量门禁。
- 不允许用“兜底回复”掩盖 graph 状态、LLM 输出、事件排序等真实问题。
- 前端实时流和历史回放必须使用同一套事件语义。

## 一键质量门禁

每次提交前运行：

```bash
bash scripts/quality-check.sh
```

等价于：

```bash
cd backend
uv run python -m unittest test.test_agent_event_store test.test_agent_v1 test.test_subject_registry

cd ../frontend
pnpm run lint
pnpm run build
```

通过标准：

- 所有后端测试通过。
- 前端 lint 无错误。
- 前端生产构建通过。
- 不允许把失败测试标记 skip 来绕过。

## 自动化测试矩阵

### P0：Agent Loop 与 HITL

这些是最容易影响主体验的核心链路，必须自动化覆盖。

| 用例 | 输入/场景 | 期望结果 | 当前覆盖位置 |
| --- | --- | --- | --- |
| LLM 调用工具后成功回答 | 用户明确提到已有成员，例如“帮爸爸看报告” | `ToolMessage` 被 LLM 使用后，最终有 `message.assistant.completed` | `backend/test/test_agent_v1.py` |
| 工具要求用户选择 | 用户说“帮家人存报告” | graph 产生 interrupt，interaction 为 `select_one` | `backend/test/test_agent_v1.py` |
| 用户选择已有成员后 resume | 选择“妈妈” | resume 后进入 LLM 生成最终回复，不重复要求选择 | `backend/test/test_agent_v1.py` |
| 用户选择新建人物/宠物 | 选择“新建人物”或“新建宠物” | 第二次 interrupt 要求输入名称 | `backend/test/test_agent_v1.py` |
| 输入名称后完成新建 | 输入“婆婆/老公/小橘” | 创建 subject，确认对象，最终 LLM 回复 | `backend/test/test_agent_v1.py` |
| LLM 空回复 | resume 后 LLM 返回空字符串 | 标记为 `error`，不能伪装 completed，不能兜底拼回复 | `backend/test/test_agent_v1.py` |
| handoff 不产生多 system message | resume 后注入确定性结果 | LLM 输入里只有一条 system message，避免模型服务 400 | `backend/test/test_agent_v1.py` |
| handoff 精准过滤旧 tool 轨迹 | 旧 `ToolMessage(needs_user_selection)` 已被用户选择解决 | 最终 LLM 不再看到旧 pending tool，但保留正常 user/assistant 历史 | `backend/test/test_agent_v1.py` |
| handoff 兼容 dict 形态 tool 轨迹 | 历史消息里存在 dict `tool_calls` / `role=tool` | 旧 pending 工具轨迹被过滤，正常对话历史保留 | `backend/test/test_agent_v1.py` |
| 最新工具 observation 进入 LLM | 工具返回 `capability_missing` | 下一轮 LLM 能看到该 observation 并生成最终自然语言，不陷入空回答 | `backend/test/test_agent_v1.py` |
| capability 按 turn 去重 | 同一用户消息内重复调用已满足能力 | runtime 返回 `already_satisfied`，不重复执行真实工具 | `backend/test/test_agent_v1.py` |
| 多轮允许重复 capability | 同一 thread 新一轮用户换对象 | `turn_key` 不同，允许再次调用同一个 capability | `backend/test/test_agent_v1.py` |

### P0：事件协议与实时顺序

| 用例 | 输入/场景 | 期望结果 | 当前覆盖位置 |
| --- | --- | --- | --- |
| conversation 级 seq 持久化 | 旧会话已有 5 条事件，新 run 内 seq 为 1/2 | 写库后 seq 为 6/7 | `backend/test/test_agent_event_store.py` |
| SSE 使用 conversation 级 seq | 旧会话已有事件，新 run 流式返回 | 前端收到的实时事件 seq 与历史回放一致 | `backend/test/test_agent_event_store.py` |
| event upsert | 同一个 event_id 再次返回 | 前端更新原事件，不重复 append | 前端逻辑，后续建议补 Vitest |
| pending interrupt 完成 | resume 后 | 旧 `interrupt.requested` 从 pending 变 completed | `backend/test/test_agent_event_store.py` |
| `interrupt.resumed` 记录 | 用户完成选择/输入 | 过程卡片中有用户已确认事件 | `backend/test/test_agent_v1.py` |
| 实时与历史事件归一化一致 | SSE 实时展示后刷新页面 | 过程卡片数量、可见步骤、顺序与刷新前一致 | `frontend/test/agentEventTimeline.test.ts` + 手工验收 |
| Markdown 助手正文 | LLM 返回标题、列表、表格、代码块 | assistant 气泡按 Markdown 展示，用户消息仍按纯文本展示 | 前端 build/lint + 手工验收 |

### P0：主体识别

| 用例 | 输入/场景 | 期望结果 | 当前覆盖位置 |
| --- | --- | --- | --- |
| 明确成员 | “帮妈妈存报告” | 识别为妈妈 | `backend/test/test_agent_v1.py` |
| 第一人称主语 | “帮我看下我上次吃的什么药” | 识别为“我”，不弹成员选择 | `backend/test/test_agent_v1.py` |
| 所有格不是本人 | “我的猫咪” | 识别为宠物，不误判为“我” | `backend/test/test_agent_v1.py` |
| 所有格亲属不是本人 | “我的妈妈上次体检报告” | 识别为妈妈，不走“我本人”捷径 | `backend/test/test_agent_v1.py` |
| 模糊对象 | “帮家人存报告” | 进入选择，而不是猜一个人 | `backend/test/test_agent_v1.py` |
| 非健康主体 | “我的手机” | `not_applicable` | `backend/test/test_agent_v1.py` |

### P0：成员与别名数据库

| 用例 | 输入/场景 | 期望结果 | 当前覆盖位置 |
| --- | --- | --- | --- |
| alias 规范化 | 全角/半角、大小写、空格差异 | `normalized_alias` 一致 | `backend/test/test_subject_registry.py` |
| 重复 alias | 同 owner 下重复别名 | 抛出 `DuplicateAliasError` | `backend/test/test_subject_registry.py` |
| agent 新建成员遇到重复 alias | HITL 输入已有别名，例如“爷爷” | tool 返回结构化 `error`，过程事件可展示错误 | `backend/test/test_agent_v1.py` |
| 已归档 alias | 历史归档别名 | 不应阻塞新建同名 alias | `backend/test/test_subject_registry.py` |
| 展示 subject 全字段 | 成员管理页 | 字段展示清楚，空值为 `-` | 前端人工验收，后续建议补组件测试 |

### P1：前端交互

这些当前主要靠 lint/build 和 Chrome 人工验证，后续建议引入 Playwright 或 Vitest。

| 用例 | 操作 | 期望结果 |
| --- | --- | --- |
| 新消息实时显示 | 输入任意消息并发送 | 用户消息立即出现，不空等 |
| 本地过程占位清理 | 后端真实事件返回 | “正在理解需求”占位被替换或移除 |
| 历史加载 | 点击历史会话 | 时间线顺序和刷新后一致 |
| 当前流式顺序 | 在已有会话继续发消息 | 新消息出现在旧消息后，不插到旧过程前 |
| interrupt 卡片 | 后端返回 pending interrupt | 输入框 disabled，完成选择后恢复 |
| error 展示 | 后端返回 `status=error` | 页面显示错误，不静默结束 |

## 手工验收脚本

每次改 Agent/HITL/事件流后，至少手工跑以下 6 条。

| 编号 | 用户输入/操作 | 期望结果 |
| --- | --- | --- |
| M1 | `帮我看下我上次吃的什么药` | 不弹成员选择；如果查询工具未实现，应明确说明未接入，而不是卡住 |
| M2 | `看下我奶奶的报告`，选择新建人物，输入 `奶奶` | 过程显示已新建奶奶；最终回复不再要求选择对象 |
| M3 | 在同一会话继续输入 `晚点我发给你` | 消息出现在上一轮之后，顺序不乱 |
| M4 | 刷新页面后点击该历史会话 | 顺序与实时等待时一致 |
| M5 | `我的猫咪` | 识别/选择宠物，不误判为“我” |
| M6 | 已有 `爷爷` alias 后再新建 `爷爷` | 如果 active alias 冲突，显示明确错误；如果已归档，不应误报冲突 |

## 评分标准

总分 100 分。每次较大改动后可以按这个表打分。

| 维度 | 分值 | 评分标准 |
| --- | ---: | --- |
| 自动化测试通过 | 25 | 一键质量门禁全部通过得满分；任一失败为 0 |
| Agent Loop 正确性 | 20 | LLM→Tool→HITL→Resume→LLM→END 路径清晰；无重复工具调用、无空 completed、无兜底伪成功 |
| 事件协议一致性 | 20 | 实时流和历史回放顺序一致；event_id upsert；pending/resumed 状态正确 |
| 用户体验 | 15 | 不空等、不乱序、不重复提问；错误可见；过程可折叠 |
| 数据一致性 | 10 | subject/alias 唯一性、归档、编辑行为符合预期 |
| 可维护性 | 10 | 新工具遵守统一返回协议；测试覆盖新分支；不把临时业务特例写进通用 prompt |

评分门槛：

- 90 分以上：可以提交或继续下一阶段。
- 80-89 分：可以本地继续开发，但不建议合并。
- 80 分以下：先修质量问题，不继续叠功能。
- P0 任一失败：无论总分多少，都不能提交。

## 新增工具时必须补的测试

以后每加一个 tool，至少补以下测试：

- tool 成功返回结构化结果。
- tool 需要用户确认时返回 `needs_user_*`、`pending_action`、`interaction`。
- continuation handler 能处理用户选择/确认/输入。
- resume 后最终 LLM 不看到旧 pending ToolMessage。
- resume 后最终 LLM 不看到旧 dict `tool_calls` / `role=tool` pending 轨迹。
- 正常完成的工具 observation 必须进入下一轮 LLM 上下文，不能被 pending trace 清理逻辑误删。
- 如果工具完成了可复用子目标，需要写入 `satisfied_capabilities[capability]`，并验证同一 turn 内重复调用返回 `already_satisfied`。
- 验证同一 thread 新一轮用户消息可以再次调用相同 capability。
- runtime 能把工具结果映射为正确 `work_item_type` 和事件。
- 前端能显示过程卡片、interrupt 卡片和最终回复。

## 新增前端交互时必须补的测试

当前前端还没有 Vitest/Playwright，暂时用 lint/build + Chrome 手工验收。建议下一阶段补：

- `mergeAgentEvents` 单元测试。
- `extractPendingInterrupt` 单元测试。
- `ChatTimeline` 分组渲染测试。
- Markdown assistant 气泡渲染测试：列表、表格、链接、代码块。
- 历史事件加载必须复用实时事件 reducer，不允许绕过过滤/去重逻辑。
- Playwright e2e：发送消息、完成 interrupt、刷新历史、继续对话。

## 不允许的做法

- 不允许用兜底助手回复掩盖 LLM 空输出。
- 不允许在通用系统 prompt 中写某个单一 tool 的业务特例。
- 不允许让前端靠文本内容判断流程状态，必须依赖事件协议字段。
- 不允许实时流和历史回放使用不同排序语义。
- 不允许跳过失败测试继续提交。

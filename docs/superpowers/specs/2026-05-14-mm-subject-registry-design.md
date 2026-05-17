# Memomed `mm_` Subject Registry 技术设计

日期：2026-05-14

## 背景

旧数据库表 `patients`、`medical_reports`、`report_chunks` 会继续保留，但从新的 Agent/报告管理体系开始不再作为事实源使用。

新体系使用统一 `mm_` 前缀，避免旧表语义和新架构混淆。

第一阶段只落地“家庭成员/宠物健康档案主体识别”所需的主体注册表：

```text
mm_care_subjects
mm_care_subject_aliases
```

后续报告全文、Markdown、用药提醒、RAG 索引也都使用 `mm_` 前缀。

## 设计原则

- 数据库是事实源，LLM 只做 grounding 和候选匹配。
- LLM 不能凭空发明主体 ID，只能匹配数据库已存在的 active subject。
- 用户要求新增人物/宠物时，必须通过 HITL continuation handler 写库。
- 别名必须可人工维护，避免 AI 识别错误无法修正。
- 新旧表隔离，旧表不做迁移、不删除、不继续扩展。

## 表结构

### `mm_care_subjects`

健康档案主体表，可以是人，也可以是宠物。

```text
id UUID primary key
owner_user_id varchar(64) not null default 'default'
subject_type varchar(20) not null
display_name varchar(100) not null
legal_name varchar(100) nullable
relation_type varchar(30) nullable
species varchar(30) nullable
breed varchar(100) nullable
gender varchar(20) nullable
birth_date date nullable
status varchar(20) not null default 'active'
notes text nullable
created_at timestamptz not null
updated_at timestamptz not null
```

字段说明：

| 字段 | 类型 | 是否必填 | 含义 | 示例 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `UUID` | 是 | 健康档案主体唯一 ID | `8f3a...` | 后续报告、用药提醒、别名都会通过该 ID 关联主体。 |
| `owner_user_id` | `varchar(64)` | 是 | 该主体属于哪个 Memomed 用户 | `default` | 第一版单用户固定为 `default`；未来多账号时可替换为真实用户 ID。 |
| `subject_type` | `varchar(20)` | 是 | 主体类型 | `human` / `pet` | 目前只允许 `human`、`pet`。 |
| `display_name` | `varchar(100)` | 是 | 前端和对话中展示的名称 | `妈妈`、`小橘` | 这是用户最常看到的名字，可以人工修改。 |
| `legal_name` | `varchar(100)` | 否 | 真实姓名或正式名称 | `吴某某` | 人类成员可选；宠物一般为空。第一版不强制填写。 |
| `relation_type` | `varchar(30)` | 否 | 该主体和用户的关系 | `self`、`mother`、`pet` | 建议值：`self`、`mother`、`father`、`spouse`、`child`、`pet`、`other`。 |
| `species` | `varchar(30)` | 否 | 宠物物种 | `cat`、`dog` | 人类主体为空；宠物建议值：`cat`、`dog`、`other`。 |
| `breed` | `varchar(100)` | 否 | 宠物品种 | `英短`、`金毛` | 非必填，用于补充宠物档案。 |
| `gender` | `varchar(20)` | 否 | 性别 | `female`、`male`、`unknown` | 第一版不强制枚举，但建议收敛为固定值。 |
| `birth_date` | `date` | 否 | 出生日期 | `2020-03-12` | 可用于年龄相关的医疗提醒和回答。 |
| `status` | `varchar(20)` | 是 | 主体状态 | `active` / `archived` | 默认 `active`；不建议物理删除主体，归档更安全。 |
| `notes` | `text` | 否 | 人工备注 | `长期关注血糖` | 存放轻量备注，不建议存报告正文。 |
| `created_at` | `timestamptz` | 是 | 创建时间 | `2026-05-14T10:00:00+08:00` | 数据审计字段。 |
| `updated_at` | `timestamptz` | 是 | 最近更新时间 | `2026-05-14T10:10:00+08:00` | 主体信息编辑时更新。 |

### `mm_care_subject_aliases`

健康档案主体别名表。

```text
id UUID primary key
subject_id UUID not null references mm_care_subjects(id) on delete cascade
owner_user_id varchar(64) not null default 'default'
alias varchar(100) not null
normalized_alias varchar(100) not null
source varchar(20) not null default 'user'
status varchar(20) not null default 'active'
created_at timestamptz not null
```

字段说明：

| 字段 | 类型 | 是否必填 | 含义 | 示例 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `UUID` | 是 | 别名记录唯一 ID | `9a2b...` | 用于编辑、归档单个别名。 |
| `subject_id` | `UUID` | 是 | 该别名属于哪个主体 | `mm_care_subjects.id` | 外键引用 `mm_care_subjects(id)`，主体归档或删除策略由业务控制。 |
| `owner_user_id` | `varchar(64)` | 是 | 该别名属于哪个 Memomed 用户 | `default` | 冗余保存，主要用于建立同一 owner 下 active alias 唯一约束。 |
| `alias` | `varchar(100)` | 是 | 用户可见的原始别名 | `老妈`、`我的猫咪`、`小橘` | 保留用户输入时的自然表达，用于前端展示和人工编辑。 |
| `normalized_alias` | `varchar(100)` | 是 | 机器匹配用的标准化别名 | `老妈`、`我的猫咪`、`小橘` | 由 `alias` 规范化得到，用于唯一约束、精确匹配和召回候选，不直接展示给用户。 |
| `source` | `varchar(20)` | 是 | 别名来源 | `user`、`ai`、`system` | `user` 表示用户手动添加；`ai` 表示 AI 建议后经用户确认；`system` 表示系统初始化。 |
| `status` | `varchar(20)` | 是 | 别名状态 | `active` / `archived` | 默认 `active`；别名不用时归档，避免破坏历史记录。 |
| `created_at` | `timestamptz` | 是 | 创建时间 | `2026-05-14T10:00:00+08:00` | 数据审计字段。 |

`alias` 和 `normalized_alias` 的区别：

- `alias` 是“人看的原始文本”，应该尽量保留用户输入或用户确认后的表达。例如用户输入 ` 我的猫咪 `，前端可以展示为 `我的猫咪`。
- `normalized_alias` 是“机器匹配和数据库约束用的规范化文本”，用于判断两个别名是否实际相同。例如 ` 我的猫咪 `、`我的 猫咪`、`我的猫咪` 可以按规则归一成同一个值。
- 第一版建议的 normalize 规则：去除首尾空格、合并连续空白、统一大小写、统一全角半角标点。中文本身不做复杂分词，避免误伤。
- 数据库唯一约束应该建在 `normalized_alias` 上，而不是 `alias` 上。这样用户虽然可能输入不同格式，但系统能识别它们是同一个别名。
- 前端编辑时主要展示和修改 `alias`；保存时后端重新计算 `normalized_alias`，不要让用户手动编辑 `normalized_alias`。

## 约束和索引

```text
idx_mm_care_subjects_owner_status(owner_user_id, status)
idx_mm_care_subjects_type(subject_type)
idx_mm_care_subject_aliases_subject_id(subject_id)
idx_mm_care_subject_aliases_normalized_alias(normalized_alias)
unique(subject_id, normalized_alias)
unique(owner_user_id, normalized_alias) where status = 'active'
```

`owner_user_id` 第一版固定为 `default`，避免 PostgreSQL unique index 中 `NULL` 不冲突的问题。

## Agent Grounding 流程

`resolve_patient_tool` 执行时：

```text
1. 查询 mm_care_subjects active 主体。
2. 查询每个主体 active aliases。
3. 把候选主体列表交给 LLM structured classifier。
4. LLM 只能返回 matched_subject_id 或 ambiguous/not_applicable。
5. 高置信度且 matched_subject_id 存在于数据库候选中，返回 success。
6. 低置信度、多候选、主体不存在，返回 needs_user_selection。
7. 用户选择新建人物/宠物时，后续 continuation handler 写入 mm_care_subjects 和 mm_care_subject_aliases。
```

## 前端影响

后续会新增 Subject Registry 页面：

```text
/subjects
```

第一版页面能力：

- 展示 active 家庭成员和宠物。
- 新增人物/宠物。
- 编辑展示名、关系、物种、别名。
- 归档主体或别名。

聊天页的 interrupt 选项不再写死，而是来自 `mm_care_subjects` 和 `mm_care_subject_aliases`。

## 后续扩展

报告全文与 Markdown 存储会使用新表：

```text
mm_medical_reports
mm_report_documents
mm_report_pages
mm_report_chunks
```

其中 `mm_medical_reports.subject_id` 会引用 `mm_care_subjects.id`，不再使用旧 `patients.id`。

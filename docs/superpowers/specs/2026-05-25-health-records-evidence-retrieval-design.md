# Memomed 企业级报告知识库与 RAG 检索设计

日期：2026-05-26

## 设计目标

Memomed 的报告 RAG 目标不是“把报告切片丢进向量库然后相似度搜索”，而是在家庭成员、报告类型、时间范围、来源页码都可控的前提下，回答有依据、可追溯、可拒答的医疗报告问题。

这份设计希望数据库结构一次到位，代码实现可以分阶段推进。

核心目标：

- 支持一份逻辑报告由一个 PDF、一张图片或多张图片组成。
- 原始 PDF/图片、页图、Markdown 文档放对象存储。
- 数据库存业务 metadata、结构化事实、层级索引、关键词索引、语义索引。
- 支持关键词查询、语义查询、结构化指标查询和混合召回。
- Agent 回答必须带 evidence pack，能追溯到报告、页码、Markdown 锚点和原图。
- 无证据时拒答或澄清，不编造。

## 核心原则

- **对象存储是文档事实源**：原始文件、页图、OCR layout、`original.md`、`current.md` 都放对象存储。
- **数据库是业务状态和索引层**：数据库保存 URI、hash、metadata、结构化事实、outline、chunk、FTS/vector 索引。
- **Markdown 不进数据库全文**：数据库只保存 Markdown URI 和 hash；页面查看/编辑时从对象存储读写。
- **chunk 不是事实源**：chunk 是从 `current.md` 派生的检索材料，可以随时重建。
- **结构化事实优先**：指标、诊断、药名、医生建议等进入事实表，用 SQL 支持精确查询和趋势分析。
- **检索先过滤再召回**：先按主体、报告类型、时间范围过滤，再做 keyword/vector 检索。
- **证据可追溯**：每条 evidence 必须能回到 report、page、source file、Markdown anchor。

## 对象存储布局

建议对象路径：

```text
u/{owner_user_id}/r/{report_id}/source/{file_id}.{ext}
u/{owner_user_id}/r/{report_id}/pages/001.png
u/{owner_user_id}/r/{report_id}/pages/001-thumb.png
u/{owner_user_id}/r/{report_id}/layout/001.json
u/{owner_user_id}/r/{report_id}/md/original.md
u/{owner_user_id}/r/{report_id}/md/current.md
```

含义：

- `source/`：用户上传的原始 PDF 或图片，不覆盖。
- `pages/`：报告页图和缩略图，用于页面预览、citation、原图溯源。
- `layout/`：OCR 坐标、表格区域、段落区域等机器解析结果。
- `md/original.md`：机器初次解析出的 Markdown。
- `md/current.md`：用户修正后的当前最新版 Markdown。

当前没有真实多租户时，`owner_user_id` 先使用数据库里的默认值 `default`。路径里不放 `subject_id`，因为报告归属以后可能被修正；归属关系以数据库字段为准，避免对象 key 迁移。

`source/` 和 `pages/` 的区别：

```text
source/ = 原始上传物，回答“用户当时上传了什么原件”
pages/  = 标准化后的报告页展示物，回答“这份逻辑报告第 N 页长什么样”
```

例如用户上传一个 PDF：

```text
u/default/r/{report_id}/source/{file_id}.pdf
u/default/r/{report_id}/pages/001.png
u/default/r/{report_id}/pages/002.png
```

`pages/` 里的图片由系统从 PDF 渲染生成。用户上传多张图片时，也建议统一生成 `pages/001.png` 这类标准页图；即使它和原图内容相同，前端和 citation 也只需要读 `mm_report_pages.image_uri`。

页图生成不使用大模型，而使用确定性图像工具：

```text
PDF -> 页图 PNG：PyMuPDF / fitz
图片 -> 标准页图和缩略图：Pillow
OCR / 多模态理解 / 字段抽取：模型或 OCR 服务
```

原因：

- PDF 渲染和缩略图生成必须稳定、便宜、可复现。
- 同一个 PDF 每次渲染出的页数和页图应一致，方便测试和追溯。
- 大模型只负责理解内容，不负责忠实渲染原文件。

## 数据库总览

核心表：

```text
mm_reports
  逻辑报告主表，保存归属、报告类型、日期、Markdown URI/hash、索引状态。

mm_report_files
  原始上传文件表，支持一份报告多张图、一次上传多份报告。

mm_report_pages
  报告页表，建立逻辑页码、原始文件、页图之间的映射。

mm_report_facts
  结构化事实表，保存指标、诊断、药名、医生建议等。

mm_report_outline_nodes
  Page/tree index，保存文档层级结构和章节定位。

mm_report_chunks
  RAG chunk 索引表，同时支持 tsvector 关键词检索和 pgvector 语义检索。
```

关系示意：

```text
mm_reports 1 ── n mm_report_files
mm_reports 1 ── n mm_report_pages
mm_reports 1 ── n mm_report_facts
mm_reports 1 ── n mm_report_outline_nodes
mm_reports 1 ── n mm_report_chunks

mm_report_files 1 ── n mm_report_pages
mm_report_pages 1 ── n mm_report_facts
mm_report_outline_nodes 1 ── n mm_report_chunks
```

## `mm_reports`

逻辑报告主表。一条记录表示一份医学文档，例如“一份出院小结”或“一份血脂报告”。它不等于一个物理文件。

| 字段 | 类型 | 必要含义 |
| --- | --- | --- |
| `id` | uuid primary key | 逻辑报告 ID。 |
| `owner_user_id` | varchar(64) | 所属用户，当前默认 `default`。 |
| `workspace_id` | varchar(64) nullable | 家庭空间或工作区 ID，未来支持家庭共享。 |
| `subject_id` | uuid | 归属健康档案主体，引用 `mm_care_subjects.id`。 |
| `upload_batch_id` | varchar(100) nullable | 上传批次 ID，用于追溯多图上传和分组。 |
| `source_kind` | varchar(30) | 来源形态：`single_pdf`、`single_image`、`multi_image`、`mixed_files`。 |
| `canonical_file_uri` | text nullable | 代表性文件 URI，例如合并 PDF、第一页图片或主文件。 |
| `report_title` | text nullable | 报告标题，例如“出院小结”“血脂四项”。 |
| `report_type` | varchar(80) nullable | 报告类型，例如 `discharge_summary`、`blood_lipid`、`liver_function`。 |
| `report_date` | date nullable | 报告日期，用于时间范围过滤。 |
| `hospital_name` | text nullable | 医院名称。 |
| `department_name` | text nullable | 科室名称。 |
| `doctor_name` | text nullable | 医生名称，可选。 |
| `original_markdown_uri` | text nullable | 初始 Markdown 对象存储 URI。 |
| `original_markdown_sha256` | varchar(64) nullable | 初始 Markdown hash。 |
| `current_markdown_uri` | text nullable | 当前 Markdown 对象存储 URI。 |
| `current_markdown_sha256` | varchar(64) nullable | 当前 Markdown hash，用于判断索引是否过期。 |
| `is_edited` | boolean | 用户是否编辑过当前 Markdown。 |
| `parse_status` | varchar(30) | 解析状态：`pending`、`parsed`、`failed`、`needs_review`。 |
| `review_status` | varchar(30) | 审核状态：`unreviewed`、`reviewed`、`corrected`。 |
| `index_status` | varchar(30) | 索引状态：`not_indexed`、`indexed`、`stale`、`failed`。 |
| `last_indexed_sha256` | varchar(64) nullable | 最近一次完成索引的 Markdown hash。 |
| `last_indexed_at` | timestamptz nullable | 最近一次完成索引的时间。 |
| `confidence` | numeric nullable | 机器解析整体置信度。 |
| `parse_notes` | text nullable | 解析异常、缺字段、待确认事项。 |
| `created_at` | timestamptz | 创建时间。 |
| `updated_at` | timestamptz | 更新时间。 |
| `archived_at` | timestamptz nullable | 归档时间，归档后默认不参与检索。 |

索引过期判断：

```text
current_markdown_sha256 != last_indexed_sha256
```

审核状态触发规则：

```text
unreviewed = 机器解析后还没有人工确认
reviewed   = 用户看过并确认 metadata / Markdown / 页序基本正确
corrected  = 用户修改过 Markdown、metadata、页序或结构化事实
```

建议触发审核或保持 `unreviewed` 的场景：

- 解析置信度低，例如页序混乱、报告类型不明确、日期缺失。
- 关键 metadata 不确定，例如 subject、report_date、hospital、report_type。
- 多图上传需要确认哪些图片属于同一份报告。
- 结构化事实风险较高，例如异常指标、用药、诊断、出院医嘱。
- Agent 查询时引用了未审核报告，最终回答应提示“该报告尚未人工核对”。

第一版可以简单处理：解析完成默认 `unreviewed`；用户点击确认后为 `reviewed`；用户编辑保存后为 `corrected`，同时 `index_status = stale`。

## `mm_report_files`

原始上传文件表。它保存用户实际上传的每个文件。一份长出院小结可以由多张图片组成，因此多条 file 可以归属同一个 report。

| 字段 | 类型 | 必要含义 |
| --- | --- | --- |
| `id` | uuid primary key | 原始文件 ID。 |
| `report_id` | uuid nullable | 归属的逻辑报告；未分组前可以为空。 |
| `owner_user_id` | varchar(64) | 所属用户。 |
| `subject_id` | uuid nullable | 预估或确认的主体；未确认前可以为空。 |
| `upload_batch_id` | varchar(100) nullable | 一次上传批次 ID。 |
| `original_order` | integer | 用户上传顺序，辅助页序判断。 |
| `file_uri` | text | 原始文件对象存储 URI。 |
| `thumbnail_uri` | text nullable | 缩略图 URI。 |
| `filename` | text nullable | 用户上传时的文件名。 |
| `mime_type` | varchar(100) nullable | 文件 MIME 类型，例如 `image/png`、`application/pdf`。 |
| `sha256` | varchar(64) nullable | 原始文件 hash，用于去重和校验。 |
| `file_size_bytes` | bigint nullable | 文件大小。 |
| `group_status` | varchar(30) | 分组状态：`ungrouped`、`auto_grouped`、`confirmed`、`rejected`。 |
| `group_confidence` | numeric nullable | 自动分组置信度。 |
| `page_number_hint` | integer nullable | 模型或用户确认的页码提示。 |
| `created_at` | timestamptz | 创建时间。 |
| `updated_at` | timestamptz | 更新时间。 |

例子：

```text
upload_batch_id = batch_001

IMG_001.png -> report A 出院小结 page 1
IMG_002.png -> report A 出院小结 page 2
IMG_003.png -> report A 出院小结 page 3
IMG_004.png -> report B 血脂报告 page 1
```

## `mm_report_pages`

报告页表。一条记录表示逻辑报告中的一页，用于建立页码、原始文件、页图、事实和 chunk 的关联。

| 字段 | 类型 | 必要含义 |
| --- | --- | --- |
| `id` | uuid primary key | 报告页 ID。 |
| `report_id` | uuid | 所属逻辑报告。 |
| `source_file_id` | uuid nullable | 来源原始文件；PDF 拆页时多页可指向同一个 file。 |
| `owner_user_id` | varchar(64) | 所属用户。 |
| `subject_id` | uuid | 所属健康档案主体。 |
| `page_number` | integer | 逻辑报告内页码，从 1 开始。 |
| `image_uri` | text nullable | 页面图片 URI；图片上传可指原图，PDF 可指渲染页图。 |
| `thumbnail_uri` | text nullable | 页面缩略图 URI。 |
| `source_file_page_number` | integer nullable | 如果来源是 PDF，表示 PDF 内部页码。 |
| `layout_uri` | text nullable | OCR 坐标、表格、段落区域 JSON 的对象存储 URI。 |
| `created_at` | timestamptz | 创建时间。 |
| `updated_at` | timestamptz | 更新时间。 |

这里不保存 `ocr_text`。OCR 文本进入 `original.md`；版面坐标进入 `layout_uri` 指向的 JSON 文件。

页图生成与关联规则：

- PDF 上传时，`mm_report_files.file_uri` 指向原始 PDF；系统把 PDF 每页渲染为 `pages/001.png`、`pages/002.png`，并写入 `mm_report_pages.image_uri`。
- 多图上传时，每张原图是一条 `mm_report_files`；系统按确认后的页序生成对应 `mm_report_pages`，`image_uri` 可以指向标准化后的 `pages/{page_number}.png`。
- `source_file_id` 负责从逻辑页追溯到原始上传文件。
- `source_file_page_number` 负责从逻辑页追溯到 PDF 内部页码。

工具选择：

- PDF 渲染使用 PyMuPDF（`fitz`），负责读取页数、逐页渲染 PNG。
- 图片标准化和缩略图使用 Pillow，负责方向校正、压缩、缩略图生成。
- OCR 和报告内容理解在页图生成之后执行，可以接 OCR 服务或多模态模型。

PDF 示例：

```text
mm_report_files:
  id = file_pdf_1
  file_uri = u/default/r/report_1/source/file_pdf_1.pdf

mm_report_pages:
  page_number = 1
  source_file_id = file_pdf_1
  source_file_page_number = 1
  image_uri = u/default/r/report_1/pages/001.png

  page_number = 2
  source_file_id = file_pdf_1
  source_file_page_number = 2
  image_uri = u/default/r/report_1/pages/002.png
```

## `mm_report_facts`

结构化事实表。它保存指标、诊断、药名、医生建议等，服务精确查询和趋势分析。它对应早期设计里的 `Metric-level extraction`。

| 字段 | 类型 | 必要含义 |
| --- | --- | --- |
| `id` | uuid primary key | 事实 ID。 |
| `owner_user_id` | varchar(64) | 所属用户。 |
| `subject_id` | uuid | 所属健康档案主体。 |
| `report_id` | uuid | 来源报告。 |
| `page_id` | uuid nullable | 来源页。 |
| `fact_type` | varchar(50) | 事实类型：`lab_result`、`diagnosis`、`medication`、`procedure`、`doctor_advice`、`body_part`。 |
| `name` | text | 原始名称，例如“甘油三酯”“脂肪肝”“阿司匹林”。 |
| `normalized_name` | text nullable | 规范化名称，用于同义词和趋势聚合。 |
| `value_text` | text nullable | 文本值，例如“轻度脂肪肝”。 |
| `value_numeric` | numeric nullable | 数值型结果，例如 `2.31`。 |
| `unit` | text nullable | 单位，例如 `mmol/L`。 |
| `reference_range` | text nullable | 参考范围。 |
| `abnormal_flag` | varchar(30) nullable | 异常标记：`high`、`low`、`positive`、`negative`、`normal`。 |
| `observed_at` | date nullable | 事实发生日期，通常等于报告日期。 |
| `source_quote` | text nullable | 来自 Markdown 的短引用，用于解释和 citation。 |
| `markdown_anchor` | text nullable | 当前 Markdown 中的锚点，用于点击跳转。 |
| `confidence` | numeric nullable | 抽取置信度。 |
| `review_status` | varchar(30) | 审核状态：`unreviewed`、`reviewed`、`corrected`。 |
| `created_at` | timestamptz | 创建时间。 |
| `updated_at` | timestamptz | 更新时间。 |

例子：

```text
fact_type = lab_result
name = 甘油三酯
normalized_name = triglyceride
value_numeric = 2.31
unit = mmol/L
abnormal_flag = high
source_quote = 甘油三酯 2.31 mmol/L ↑
```

## `mm_report_outline_nodes`

Page/tree index 表。它保存报告的层级结构，让检索可以先定位章节，再读取相关 chunk，而不是只靠 embedding 盲搜。

| 字段 | 类型 | 必要含义 |
| --- | --- | --- |
| `id` | uuid primary key | outline 节点 ID。 |
| `report_id` | uuid | 所属报告。 |
| `owner_user_id` | varchar(64) | 所属用户。 |
| `parent_id` | uuid nullable | 父节点 ID，用于构建树。 |
| `node_path` | text | 稳定路径，例如 `1/2/3`，用于排序和定位。 |
| `node_type` | varchar(50) | 节点类型：`document`、`page`、`section`、`table`、`metric_group`、`doctor_opinion`、`recommendation`。 |
| `heading` | text nullable | 节点标题，例如“出院诊断”“检查结果”。 |
| `page_start` | integer nullable | 起始页码。 |
| `page_end` | integer nullable | 结束页码。 |
| `markdown_anchor` | text nullable | 当前 Markdown 中的锚点。 |
| `summary` | text nullable | 该节点短摘要，用于快速筛选候选章节。 |
| `sort_order` | integer | 同级节点排序。 |
| `created_at` | timestamptz | 创建时间。 |

例子：

```text
document: 出院小结
  page: 第 1 页
    section: 入院情况
    section: 出院诊断
  page: 第 2 页
    section: 治疗经过
    section: 出院医嘱
```

## `mm_report_chunks`

RAG 检索索引表。它从当前 Markdown 和 outline 派生，承载两类索引：

- `search_vector`：PostgreSQL `tsvector`，用于关键词检索。
- `embedding`：pgvector，用于语义检索。

| 字段 | 类型 | 必要含义 |
| --- | --- | --- |
| `id` | uuid primary key | chunk ID。 |
| `owner_user_id` | varchar(64) | 所属用户。 |
| `subject_id` | uuid | 所属健康档案主体，作为第一层过滤条件。 |
| `report_id` | uuid | 来源报告。 |
| `primary_page_id` | uuid nullable | 主要来源页，用于快速跳转。 |
| `page_start` | integer nullable | chunk 覆盖的起始页码。 |
| `page_end` | integer nullable | chunk 覆盖的结束页码；跨页 section 可大于 `page_start`。 |
| `page_refs` | jsonb nullable | 精确页引用列表，例如涉及哪些 page、anchor 或 layout 区域。 |
| `outline_node_id` | uuid nullable | 来源 outline 节点。 |
| `markdown_sha256` | varchar(64) | 生成 chunk 时使用的 `current.md` hash。 |
| `chunk_type` | varchar(50) | chunk 类型：`page`、`section`、`table`、`metric`、`summary`、`doctor_opinion`。 |
| `chunk_text` | text | 派生出来的检索文本，用于 FTS、embedding 和短引用。 |
| `chunk_index` | integer | 在同一报告内的 chunk 顺序。 |
| `markdown_anchor` | text nullable | 当前 Markdown 中的锚点。 |
| `search_vector` | tsvector nullable | 全文检索向量，用于关键词查询。 |
| `embedding` | vector(1024) nullable | 语义向量，用于 pgvector 检索；当前模型固定 1024 维。 |
| `embedding_model` | varchar(100) nullable | 生成 embedding 的模型名，用于后续模型迁移和索引重建。 |
| `embedding_dimensions` | integer nullable | embedding 维度，当前固定 `1024`。 |
| `metadata` | jsonb | 低频补充信息，例如 token 数、抽取策略、表格坐标。 |
| `created_at` | timestamptz | 创建时间。 |

过期判断：

```text
mm_report_chunks.markdown_sha256 != mm_reports.current_markdown_sha256
```

过期 chunk 不参与默认检索。

embedding 维度规则：

- pgvector 字段维度要提前定义，例如当前使用 `vector(1024)`。
- 不同维度的 embedding 不能混在同一列和同一个 pgvector 索引里检索。
- 第一版按当前模型固定 `vector(1024)`。
- 后续如果切换到其他维度模型，应新增列、拆表或重建索引迁移，而不是直接混写。

## 推荐数据库索引

这些索引是为了让 RAG 的 metadata filter、关键词检索和语义检索路径稳定。

### `mm_reports`

```text
idx_mm_reports_subject_date
  (subject_id, report_date desc)

idx_mm_reports_subject_type_date
  (subject_id, report_type, report_date desc)

idx_mm_reports_owner_status
  (owner_user_id, review_status, index_status)

idx_mm_reports_upload_batch
  (upload_batch_id)
```

用途：

- 支持“妈妈最近一次肝功能”“爸爸去年体检”这类 metadata-first 查询。
- 支持上传批次回溯和报告分组排查。

### `mm_report_files`

```text
idx_mm_report_files_batch_order
  (upload_batch_id, original_order)

idx_mm_report_files_report
  (report_id)

idx_mm_report_files_sha256
  (sha256)
```

用途：

- 支持多图上传后按原顺序展示和确认页序。
- 支持原始文件去重。

### `mm_report_pages`

```text
uq_mm_report_pages_report_page
  unique (report_id, page_number)

idx_mm_report_pages_file
  (source_file_id)
```

用途：

- 保证一份逻辑报告内页码唯一。
- 支持从原图追溯到报告页。

### `mm_report_facts`

```text
idx_mm_report_facts_subject_name_date
  (subject_id, normalized_name, observed_at desc)

idx_mm_report_facts_subject_type_date
  (subject_id, fact_type, observed_at desc)

idx_mm_report_facts_report
  (report_id)
```

用途：

- 支持“最近几次甘油三酯”“2025 年血糖”“有没有脂肪肝”。
- 支持趋势分析和精确查询。

### `mm_report_outline_nodes`

```text
idx_mm_report_outline_report_path
  (report_id, node_path)

idx_mm_report_outline_report_type
  (report_id, node_type)
```

用途：

- 支持 Page/tree index 章节定位。
- 支持按“医生建议”“诊断意见”“检验表格”等节点类型召回。

### `mm_report_chunks`

```text
idx_mm_report_chunks_subject_report
  (subject_id, report_id)

idx_mm_report_chunks_report_type
  (report_id, chunk_type)

idx_mm_report_chunks_markdown_sha
  (report_id, markdown_sha256)

idx_mm_report_chunks_search_vector
  GIN (search_vector)

idx_mm_report_chunks_embedding
  HNSW or IVFFLAT (embedding)
```

用途：

- 先按 subject/report metadata 过滤，再做 FTS 或 vector 检索。
- 支持编辑 Markdown 后通过 hash 排除过期 chunk。
- 支持关键词查询和语义查询。

## 混合切片策略

不要只用固定 800 字 chunk。医疗报告更适合混合切片：

### Page-level chunk

按页切片，保留完整页上下文和页码。

适合：

- 引用来源。
- 报告页面回看。
- 出院小结、影像报告等长文本定位。

例子：

```text
chunk_type = page
page_number = 2
chunk_text = 第 2 页对应的 current.md 内容
```

### Section-level chunk

按章节切片，例如“检验项目”“影像所见”“诊断意见”“出院医嘱”。

适合：

- 语义问答。
- 医生建议、检查结论、病程摘要查询。

例子：

```text
chunk_type = section
heading = 出院医嘱
chunk_text = 低盐低脂饮食，按时服药，2 周后门诊复查...
```

跨页 section 不应该被强行切断。如果“出院医嘱”从第 2 页末尾延续到第 3 页开头，应生成一个完整 section chunk，并记录跨页来源：

```text
chunk_type = section
heading = 出院医嘱
page_start = 2
page_end = 3
primary_page_id = page_2
markdown_anchor = discharge-advice
chunk_text = 第 2 页末尾 + 第 3 页开头的完整出院医嘱
```

`page_refs` 示例：

```json
[
  {"page_id": "page-2", "page_number": 2, "anchor": "p2-block-18"},
  {"page_id": "page-3", "page_number": 3, "anchor": "p3-block-01"}
]
```

这样检索既能召回完整语义段，也能在 citation 中说明“来源：第 2-3 页，出院医嘱部分”。

### Table-level chunk

按表格切片，保留同一张检验表的上下文。

适合：

- 血常规、肝功能、血脂等表格检索。
- 避免单个指标脱离参考范围和单位。

### Metric-level extraction

不只生成 chunk，还要抽取到 `mm_report_facts`。

适合：

- “2025 年血糖是多少？”
- “甘油三酯是不是一直偏高？”
- “最近几次肝功能有什么变化？”

例子：

```text
mm_report_facts:
name = 空腹血糖
value_numeric = 6.8
unit = mmol/L
abnormal_flag = high
observed_at = 2026-03-12
```

## 检索策略

企业级检索链路：

```text
Query Understanding
→ 判断 subject / report_type / time_range / metric_or_entity
→ SQL metadata filter
→ facts 精确查询
→ outline/page tree 定位候选章节
→ keyword FTS 检索
→ pgvector 语义检索
→ RRF 融合
→ optional rerank
→ evidence pack
→ answer with citations
```

### Query Understanding

把用户问题解析成结构化检索意图。

例子：

用户问：

```text
我妈上次肝功能有没有异常？
```

解析结果：

```json
{
  "subject_hint": "妈妈",
  "report_type": "liver_function",
  "time_range": "latest",
  "question_type": "abnormal_metric_check",
  "metric_or_entity": "肝功能"
}
```

### Metadata Filter

先用 SQL 缩小范围：

```text
subject_id = 妈妈
report_type in liver_function / physical_exam
report_date = 最近一次或指定时间范围
index_status = indexed
archived_at is null
```

### Facts 精确查询

指标、药名、诊断词优先查 `mm_report_facts`。

适合：

```text
我妈妈 2025 年血糖是多少？
甘油三酯最近几次是不是偏高？
爸爸报告里有没有脂肪肝？
```

### Page/tree 定位

如果问题涉及章节或长文档，先查 `mm_report_outline_nodes`。

适合：

```text
出院小结里出院医嘱怎么写的？
影像报告的诊断意见是什么？
```

### Keyword FTS

关键词召回走 `mm_report_chunks.search_vector`。

适合：

```text
报告里有没有“脂肪肝”
哪份报告提到“低盐低脂饮食”
```

第一版关键词排序使用 PostgreSQL 内置 FTS ranking：

```text
ts_rank(search_vector, query)
ts_rank_cd(search_vector, query)
```

规则说明：

- `ts_rank` 主要看命中词频和 A/B/C/D 字段权重。
- `ts_rank_cd` 是 cover density ranking，会额外考虑 query 词之间的距离；词越集中，分数越高。
- Postgres 内置 FTS 不是真正 BM25，也不使用搜索引擎级全局 IDF/平均文档长度模型。

BM25 作为后续增强：

```text
第一版：Postgres FTS + ts_rank_cd
增强版：ParadeDB pg_search 或 OpenSearch / Elasticsearch BM25
```

区别简表：

| 维度 | `ts_rank` / `ts_rank_cd` | BM25 |
| --- | --- | --- |
| 全局稀有度 IDF | 不使用真正全局语料统计 | 使用 |
| 词频 | 使用 | 使用，并有饱和机制 |
| 文档长度 | 可选 normalization | 核心机制之一 |
| 词距 | `ts_rank_cd` 会考虑 | 标准 BM25 本身不强调词距 |
| 适合阶段 | Postgres 内置 baseline | 搜索质量增强 |

### pgvector 语义检索

语义召回走 `mm_report_chunks.embedding`。

适合：

```text
有没有和肝胆相关的异常？
医生有没有建议复查？
```

### RRF 融合与 rerank

后续同时拿 facts、FTS、vector 的候选证据，用 RRF 融合排序，再让 reranker 或 LLM 选择最相关 evidence。

第一阶段可以不做 rerank，但数据结构要支持。

RRF，即 Reciprocal Rank Fusion，按各检索器中的排名融合，不直接比较不同检索器的原始分数。

公式：

```text
RRF(d) = Σ weight_i / (k + rank_i(d))
```

含义：

- `d`：候选证据。
- `i`：检索器，例如 facts、FTS、vector、outline。
- `rank_i(d)`：候选证据在第 i 个检索器里的排名，从 1 开始。
- `k`：平滑常数，常用 `60`。
- `weight_i`：该检索器权重。

Memomed 建议初始权重：

```text
fact_weight = 1.5
keyword_weight = 1.0
vector_weight = 1.0
outline_weight = 0.8
k = 60
```

结构化 facts 更可靠，所以权重略高。相同 chunk 同时被 FTS 和 vector 召回时，用同一个 `chunk_id` 合并，让分数叠加。

例子：

```text
候选 A:
  FTS rank = 1
  vector rank = 5

A = 1/(60+1) + 1/(60+5)
  = 0.03177
```

## Evidence Pack

Agent 不直接相信模型记忆，必须基于 evidence pack 回答。

证据结构：

```json
{
  "evidence_type": "fact | keyword_chunk | semantic_chunk | outline_node",
  "report_id": "report-1",
  "report_title": "血脂四项",
  "report_type": "blood_lipid",
  "report_date": "2026-04-12",
  "hospital_name": "某医院",
  "page_number": 1,
  "page_start": 1,
  "page_end": 1,
  "page_refs": [
    {"page_id": "page-1", "page_number": 1, "anchor": "p1-table-lipids"}
  ],
  "markdown_uri": "u/default/r/report-1/md/current.md",
  "markdown_anchor": "section-lipids",
  "source_file_uri": "u/default/r/report-1/source/file-1.png",
  "page_image_uri": "u/default/r/report-1/pages/001.png",
  "excerpt": "甘油三酯 2.31 mmol/L ↑"
}
```

回答要求：

- 查到证据时说明来源，例如“2026-04-12 血脂报告，第 1 页”。
- 对异常指标只能解释报告文本含义，不做诊断。
- 无证据时说明没有在已存报告中找到，不能编造。
- 不把 `not_found` 改写成“正常”。

## 入库流程

```text
上传图片/PDF
→ 写 mm_report_files，保存每个原始文件 URI
→ 自动判断哪些文件属于同一份报告、页序如何排列
→ 需要时 HITL 确认分组和页序
→ 创建 mm_reports
→ 用 PyMuPDF/Pillow 生成标准页图和缩略图
→ 写 mm_report_pages
→ OCR / 多模态解析，生成 layout JSON 和 original.md
→ 复制 original.md 为 current.md
→ 回写 mm_reports 的 Markdown URI 和 hash
→ 抽取 mm_report_facts
→ 生成 mm_report_outline_nodes
→ 从 current.md 派生 mm_report_chunks
→ 写入 search_vector 和 embedding
→ mm_reports.index_status = indexed
```

## 编辑与重建索引流程

```text
打开报告知识库页面
→ 后端根据 current_markdown_uri 读取对象存储 Markdown
→ 用户修正 Markdown
→ 保存覆盖 current.md，并更新 current_markdown_sha256
→ mm_reports.index_status = stale
→ 手动或后台重建 facts / outline / chunks
→ mm_reports.last_indexed_sha256 = current_markdown_sha256
→ mm_reports.index_status = indexed
```

约束：

- 不覆盖原始 PDF/图片。
- 不覆盖 `original.md`。
- 不在数据库存整篇 Markdown。
- 旧 chunks 因 hash 不匹配自动失效。

## 页面形态

报告知识库页面：

```text
左侧：报告列表
  - 成员筛选
  - 报告类型筛选
  - 时间筛选
  - 审核状态 / 索引状态

中间：Markdown 文档
  - 从 current_markdown_uri 加载
  - 预览模式
  - 编辑模式
  - 保存修正
  - 显示是否已编辑、索引是否过期

右侧：原始证据
  - 原始文件列表
  - 页图 / PDF 预览
  - 页码切换
  - 后续可支持 Markdown 段落与原图区域联动
```

## 实施顺序

### 阶段一：知识库骨架

- 新增 `mm_reports`、`mm_report_files`、`mm_report_pages`。
- 新增对象存储读写服务。
- 新增报告知识库 API。
- 新增报告知识库页面，支持查看/编辑 `current.md`。

### 阶段二：关键词检索 baseline

- 新增 `mm_report_outline_nodes`、`mm_report_chunks`。
- 从 `current.md` 派生 page/section/table chunks。
- 写入 `search_vector`。
- `query_health_records_tool` 接入 `ReportKnowledgeSearchService`。

### 阶段三：结构化事实与语义检索

- 新增并填充 `mm_report_facts`。
- 支持指标精确查询和趋势查询。
- 给 chunks 写入 embedding。
- 支持 pgvector 语义检索。

### 阶段四：混合召回和评测

- FTS + vector + facts RRF 融合。
- 可选 rerank。
- 建立 30-50 条 RAG golden set。
- 评估 retrieval hit rate、metadata filter accuracy、citation accuracy、faithfulness、abstention quality。

## 测试策略

数据层：

- 多张图片可以归属同一份 report。
- 同一 upload batch 可以拆成多份 report。
- Markdown 只保存 URI 和 hash，不保存整篇正文。
- 编辑 `current.md` 后，`index_status` 变成 `stale`。
- 重建索引后，chunk 的 `markdown_sha256` 等于 report 的 `current_markdown_sha256`。

检索层：

- 精确指标问题优先命中 `mm_report_facts`。
- 关键词问题命中 `search_vector`。
- 语义问题命中 `embedding`。
- 过期 chunk 不参与默认检索。
- evidence 必须带 `report_id / page_number / markdown_uri / source_file_uri 或 page_image_uri`。

Agent 与前端：

- 报告知识库页面能打开 Markdown 和原图。
- 编辑保存后页面显示索引待更新。
- Agent 查询无证据时返回 `not_found`，不编造。
- Agent 查询有证据时最终回答带来源。
- 改 UI / streaming / HITL 后必须用真实浏览器验证关键链路。

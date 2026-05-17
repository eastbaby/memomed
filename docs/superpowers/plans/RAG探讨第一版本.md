# 对话一：设计第 5 段，企业级 RAG 怎么做**

`memomed` 的 RAG 目标不是“把报告切片丢进向量库然后相似度搜索”，而是：**在家庭成员、报告类型、时间范围、来源页码都可控的前提下，回答有依据、可追溯、可拒答的医疗报告问题。**

**1. 入库链路**

```text
上传图片/PDF
→ OCR/多模态解析
→ 报告分组与页序判断
→ 元数据抽取
→ HITL 确认关键元数据
→ 原文件入对象存储
→ 报告主表入库
→ 按页/章节/指标切片
→ embedding 入 pgvector
→ 建立 report_id / patient_id / report_type / date / page_number metadata
```

关键点：**先确认 metadata，再入向量库**。否则后面检索时就无法稳定区分“我、妈妈、爸爸”的报告。

**2. 切片策略**

不要只用固定 800 字 chunk。医疗报告更适合混合切片：

`Page-level chunk`：保留页码和原始上下文，适合引用来源。

`Section-level chunk`：按“检验项目、影像所见、诊断意见、医生建议”拆，适合语义问答。

`Metric-level extraction`：对血压、血糖、血脂、肝肾功能这类指标结构化抽取，适合趋势查询和精确比较。

所以企业级设计里应该有两份数据：

1. **原文切片**：给 RAG 用。
2. **结构化指标表**：给精确查询和趋势分析用。

**3. 检索策略**

检索不应该只有 `similarity_search(query, k=4)`。建议是：

```text
Query Understanding
→ 判断患者、报告类型、时间范围、指标名
→ SQL metadata filter
→ vector search
→ optional keyword / BM25 search
→ rerank
→ evidence pack
→ answer with citations
```

例子：

用户问：“我妈上次肝功能有没有异常？”

系统应该先解析：

```json
{
  "patient": "mother",
  "report_type": "肝功能",
  "time_range": "最近一次",
  "question_type": "abnormal_metric_check"
}
```

然后先查结构化报告元数据，确定“妈妈最近一次肝功能报告”，再在该报告范围内检索，而不是全库向量搜索。

**4. 回答策略**

回答必须带证据边界：

```text
结论：本次报告中 ALT 偏高，提示肝功能指标异常。
依据：2026-03-12，XX 医院，肝功能报告，第 2 页。
解释：ALT 升高可能和脂肪肝、饮酒、药物等多种因素有关。
建议：仅供健康管理参考，不能替代医生诊断；建议结合医生意见复查。
```

如果证据不足，要拒答或澄清：

```text
我目前没有找到妈妈最近一次肝功能报告，无法判断是否异常。你可以上传报告，或告诉我报告日期。
```

**5. RAG Eval**

这是面试加分点。你要有一套小型评测集，而不是凭感觉调 prompt。

评测维度：

`retrieval_hit_rate`：正确报告是否被召回。

`metadata_filter_accuracy`：患者、时间、报告类型是否过滤正确。

`citation_accuracy`：引用页码/报告是否真实。

`answer_faithfulness`：回答是否只基于证据，不编造。

`abstention_quality`：没证据时是否拒答/澄清。

`latency_cost`：一次 RAG 问答成本和耗时。

最小可做版本：准备 30-50 个问题，覆盖患者混淆、时间范围、报告类型、异常指标、无答案拒答。

**6. 面试表达**

> 我会把医疗 RAG 分成 metadata-first retrieval 和 evidence-grounded answering。患者、报告类型、时间范围先走结构化过滤，报告原文再走向量检索和重排。对于指标趋势类问题，我不会依赖向量召回，而是抽取到结构化指标表。最后用 citation 和小型 golden set 评估召回、忠实度和拒答质量。这样 RAG 才不是 demo，而是可治理的企业级检索系统。

下一段我建议讲 **Tool Registry + MCP + 权限/HITL**，因为这会把“企业级”和“平台化选型”讲得更完整。


# 对话二：关于rag细节

我理解的这股风，核心不是“不要 RAG”，而是反对 **把所有文档都切碎丢向量库，然后每次 query 临时拼上下文**。

**Karpathy LLM Wiki 做什么**
它的思路是：原始资料进来后，不只是存 raw chunks，而是让 LLM 把资料“编译”成一个长期维护的 Markdown wiki。

```text
raw source
→ LLM ingest
→ structured markdown pages
→ cross links / index / entity pages
→ 后续查询先读这个整理好的知识层
```

它强调“知识会积累”。传统 RAG 每次都从碎片重新理解；LLM Wiki 是先把资料整理成可读、可维护、可版本化的知识库。相关解释可以看这个实现介绍：[llm-wiki guide](https://www.cognitionus.com/blog/llm-wiki-guide) 和 [Karpathy Wiki](https://karpathy-wiki.lol/en)。

**PageIndex 做什么**
PageIndex 反的是“无脑 chunk”。它为长文档建立层级树/目录索引，让 LLM 像人翻目录一样先定位章节，再读相关部分。它主张对 PDF/Markdown/DOCX 建树状索引，而不是只靠 embedding 相似度：[PageIndex](https://www.pageindex.dev/)、[PageIndex research intro](https://pageindex.ai/research/pageindex-intro)。

所以它们共同点是：

```text
保留文档结构
用层级索引/Markdown 语义组织
减少盲目 chunk
让 LLM 在结构上推理
```

**Memomed 要不要 chunk RAG**
我建议：**要，但不要第一优先，也不要把 chunk 当事实源。**

你的场景分三类查询：

```text
1. 精确查询
“我妈妈 2025 年血糖是多少？”
更适合结构化表 + SQL，不应该靠 chunk RAG。

2. 原文查看/编辑
“打开这份体检报告全文”
应该直接读 report_documents.edited_text / ocr_text，不需要 RAG。

3. 综合问答
“我妈妈最近几次肝功能有什么变化？”
需要结构化指标 + 报告原文依据 + 可能的 RAG。
```

所以我建议架构是：

```text
PostgreSQL 事实库
  care_subjects
  medical_reports
  report_documents
  report_observations / lab_results

Markdown 原文层
  保存用户可读、可编辑的报告全文

索引层
  tsvector: 关键词检索
  page/tree index: 按报告结构定位章节
  pgvector chunks: 后续做语义检索，可选
```

**原文值不值得存 Markdown**
值得，但我不建议“只存 Markdown 文件”。更稳的方式是：

```text
PostgreSQL 存事实和最新文本
对象存储/本地文件存 markdown 快照
索引层从 PostgreSQL/Markdown 派生
```

具体可以这样：

```text
report_documents
  id
  report_id
  source_file_uri
  ocr_text
  edited_markdown
  markdown_uri
  markdown_sha256
  text_version
  created_at
  updated_at
```

文件路径例如：

```text
data/reports/{subject_id}/{report_id}/original.pdf
data/reports/{subject_id}/{report_id}/ocr.md
data/reports/{subject_id}/{report_id}/edited.md
```

数据库里存：

```text
edited_markdown 当前版本
markdown_uri 文件位置
markdown_sha256 防篡改/重建索引
```

这样前端展示直接读 DB 字段更方便；文件层适合导出、版本 diff、git-like 管理、重建索引。

**我的最终建议**
第一版不要上复杂 chunk RAG。先做：

```text
1. 报告原文转 Markdown
2. PostgreSQL 存 edited_markdown
3. 前端可查看/编辑 Markdown
4. PostgreSQL tsvector 做关键词搜索
5. 给每份报告生成 outline/page index
6. 后续再从 edited_markdown 派生 chunks + pgvector
```

一句话：**原文 Markdown 是事实层的一部分；chunk/vector 是派生索引，不是主存储。**
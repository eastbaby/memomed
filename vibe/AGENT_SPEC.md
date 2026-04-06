# 背景
1. 目前不需要修改任何前端代码
2. 目前我不通过启动unicorn fastapi来启动后端服务，而是通过uv run langgraph dev来启动一个标准的 langgraph agent server

# 需求0.0.1

基于这样的文件结构初始化agent代码
```
app/
├── agent # all project code lies within here
│   ├── utils # utilities for your graph
│   │   ├── __init__.py
│   │   ├── tools.py # tools for your graph
│   │   ├── nodes.py # node functions for your graph
│   │   └── state.py # state definition of your graph
│   ├── __init__.py
│   └── graph.py # code for constructing your graph
├── .env # environment variables
├── langgraph.json  # configuration file for LangGraph
└── pyproject.toml # dependencies for your project
```

# 需求0.0.2

1. 持久化 checkpoint，memory 到数据库，根据配置的POSTGRES_URI_CUSTOM环境变量进行持久化 (TODO 在langgraph dev启动的时候还是会走内存数据库)
2. 实现rag功能，用户输入图片报告，通过报告读取文字存入rag数据库。rag用pgvector存储，参考langgraph的官方文档 https://docs.langchain.com/oss/python/langgraph/agentic-rag



-- 1. 报告主表：存储原始信息和元数据
CREATE TABLE medical_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(50) NOT NULL,          -- 区分是爸爸还是妈妈
    report_date DATE NOT NULL,             -- 报告日期
    report_type VARCHAR(50),               -- 血检、CT、B超等
    hospital_name VARCHAR(255),            -- 医院名称
    file_path TEXT,                        -- 原始 PDF/图片路径
    summary TEXT,                          -- AI 自动生成的摘要
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. 报告切片向量表：存储用于搜索的向量
CREATE TABLE report_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID REFERENCES medical_reports(id) ON DELETE CASCADE,
    content TEXT NOT NULL,                 -- 切片文本内容
    embedding VECTOR(1536),                -- 向量字段（以 OpenAI 1536维为例）
    page_number INTEGER,                   -- 来源页码
    index_in_report INTEGER                -- 切片在原报告中的顺序
);


# 需求0.0.3 sft

- 场景描述 ：只训练一轮对话，用户输入问题，assistant返回回答。这是一个家庭健康管理agent，生成100个用户可能提问的问题，每个问题对应一个回答，回答必须用下方的basemodel格式返回。你的任务是分析用户行为，提取出后续llm统一回答的问题的关键回答点。注意这个agent会给父母使用，我希望关键回答点能带有一些提醒作用，防止我父母忘记重要信息。case1 如果用户提问有医疗相关的数据分析，我需要关键回答点中明确表示近作参考，具体以医生为准的字样。 case2 如果父母不肯吃药或者不按规则吃药，我需要关键回答点能语重心长的表达起到监督作用

- 补充要求 ：（1）用户的问题不全是以“我”开头命名的，请发散一点，生成更多样式的用户问题。（2）回答的关键要点需要精简，不需要是完整的一句话，也不需要包含任何解释，主要是生成后续的llm回答需要覆盖的关键点。

- 用户的问题需要封装为一个user content，内容为 "用户的问题是：{xxxx}, 请生成回答关键要点"。

- basemodel格式 ：明确规定assistant返回content的basemodel格式，必须为 answer_keypoints 的 json数据结构
    
    class MedicalAgentTask(BaseModel):
        """医疗助手Agent任务编排输出格式（SFT 输出结构）"""
        answer_keypoints: List[str] = Field(..., description="回答关键点，给用户的回答中必须包含的内容")

- 数据用途 ：训练agent，提取用户行为的关键回答点，用于后续的llm基于这些keypoints统一回答。
- 生成数量 ：100条
- 其他要求 ：暂无(如有特殊要求，如语言风格、难度级别等)



生成结果：
- 保存位置 ： /memomed/backend/data/Trainingdata.jsonl
数据特点：
1. 符合MedicalAgentTask格式要求 ：每条数据的assistant回复都使用了 answer_keypoints 的JSON数据结构
2. 场景覆盖全面 ：涵盖了家庭健康管理的各个方面，包括：
   
   - 血压、血糖监测与管理
   - 用药提醒与监督
   - 饮食与运动建议
   - 症状咨询与分析
   - 药物相互作用咨询
   - 健康生活方式指导
3. 关键回答点设计 ：
   
   - 医疗数据分析相关问题包含"仅供参考，具体以医生为准"的提示
   - 用药监督问题语重心长，起到提醒和监督作用
   - 所有回答都带有提醒作用，适合父母使用


模型已训练完成，name： SFT_MODEL

现在需要应用该模型到agent中，辅助最终的llm输出对应关键词


# 需求0.0.4
现在我需要进一步丰富我的agent应用。你先和我讨论一下设计。有两个维度我要做： 1. 完善rag存储和检索的流程，现在虽然定义了数据库但是没有把相关字段写上信息，无法区分是我的报告，还是我妈妈的报告，无法根据metadata检索 2. 实现用药提醒和管理功能



# 后续需求

小需求：
- hitl的拒绝模式可能要再测一测
- hitl 如果有两个图一起apporve好像和一个图的apporve结构不一样

大需求：
当前直接使用前端demo无法区分用户user_id。后续可以拓展。



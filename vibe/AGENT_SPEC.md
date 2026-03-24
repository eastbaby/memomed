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



# 后续需求

小需求：
alembic的url从env读取

大需求：
当前直接使用前端demo无法区分用户user_id。后续可以拓展。



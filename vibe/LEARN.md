
注意，当前用的embedding是用的dashscope模型，不兼容openai模型。

阿里云这页文档写得很明确：`text-embedding-v4` 支持的维度是 `2048、1536、1024、768、512、256、128、64`，`text-embedding-v3` 支持 `1024、768、512、256、128、64`。

默认是1024维度。

我现在用的langchain的包不支持自定义维度，但是因为默认是1024，数据库也定义的1024。


来源：阿里云官方文档 https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api

你现在的问题其实分两层：

1. 阿里云原生接口支持 `dimensions`
   文档里的 OpenAI 兼容调用就是：
   ```python
   client.embeddings.create(
       model="text-embedding-v4",
       input="xxx",
       dimensions=2048,
       encoding_format="float",
   )
   ```

2. 但 `langchain_community.embeddings.DashScopeEmbeddings` 这层通常**没有把这个参数暴露出来**
   所以你不能像现在这样简单写：
   ```python
   DashScopeEmbeddings(..., dimensions=2048)
   ```
   这类包装大概率不支持。

如果你想在项目里真正用 `2048` 维，最稳的做法是：

1. 不再用 `DashScopeEmbeddings`
2. 自己写一个自定义 `Embeddings` 类，底层走阿里云的 OpenAI 兼容接口
3. 把 pgvector 列从 `Vector(1024)` 改成 `Vector(2048)`
4. 重建或迁移已有向量数据

可以直接这么写一个适配器：

```python
from openai import OpenAI
from langchain_core.embeddings import Embeddings

class DashScopeCompatibleEmbeddings(Embeddings):
    def __init__(self, api_key: str, model: str = "text-embedding-v4", dimensions: int = 2048):
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.model = model
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
            encoding_format="float",
        )
        return [item.embedding for item in resp.data]

    def embed_query(self, text: str) -> list[float]:
        resp = self.client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=self.dimensions,
            encoding_format="float",
        )
        return resp.data[0].embedding
```

然后你在 [rag.py](/Users/xinhuiwu/personalProj/memomed/backend/app/agent/utils/rag.py) 里换成：

```python
embeddings = DashScopeCompatibleEmbeddings(
    api_key=settings.LLM_API_KEY,
    model=settings.EMBEDDING_MODEL,
    dimensions=2048,
)
```

同时你数据库模型这里也要改：
[models.py](/Users/xinhuiwu/personalProj/memomed/backend/app/models/models.py#L102)

把：
```python
Vector(1024)
```

改成：
```python
Vector(2048)
```

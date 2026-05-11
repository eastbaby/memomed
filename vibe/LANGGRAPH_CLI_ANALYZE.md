我把 uv run langgraph dev 这条链路读完了，结论是：

langgraph dev 启起来的服务端，运行 graph 时是以“异步服务”为主；但 LangGraph 的 graph 对象本身同时支持同步和异步两套调用接口，所以两种都能支持。只是你现在这条 langgraph dev 服务链，实际走的是 async 那套。

## 启动链路

uv run langgraph dev 先进入 CLI 的 dev() 命令：langgraph_cli/cli.py (line 1788) 

path: /Users/xinhuiwu/personalProj/memomed/backend/.venv/lib/python3.12/site-packages/langgraph_cli/cli.py

这里它做了两件事：

1. 读取 langgraph.json
2. 把里面的 graphs 映射传给 langgraph_api.cli.run_server(...)

对应代码在：
langgraph_cli/cli.py (line 1835)

run_server() 并不直接执行 graph，而是把 graphs 写进环境变量 LANGSERVE_GRAPHS，然后起 uvicorn 跑 langgraph_api.server:app：langgraph_api/cli.py (line 198), langgraph_api/cli.py (line 206)

## graph 是怎么加载的

服务启动后，langgraph_api.graph.collect_graphs_from_env() 会从 LANGSERVE_GRAPHS 里读取 graph 路径，也就是你 langgraph.json 的 "./app/agent/graph.py:graph" 这种配置：langgraph_api/graph.py (line 345)

真正取 graph 时走的是 get_graph(...)：

- 如果你导出的是 StateGraph，它会现场 compile()
- 如果你导出的是已编译对象 Pregel/CompiledGraph，直接拿来用

对应代码：
langgraph_api/graph.py (line 207)
langgraph_api/graph.py (line 249)

所以这里有个原理点：

- langgraph dev 不要求你必须导出“同步 graph”或“异步 graph”
- 它只要求能拿到一个 LangGraph graph 对象
- 之后服务层会按自己的 async 执行模型来调用它

## 服务端执行时，到底调 sync 还是 async

这点我确认了：langgraph dev 的 API 服务在 run/stream 执行 graph 时，实际调用的是异步接口。

在 langgraph_api.stream.astream_state() 里，它拿到 graph 后最终调用的是：

- graph.astream_events(...)
- 或 graph.astream(...)

见这里：
langgraph_api/stream.py (line 223)
langgraph_api/stream.py (line 369)

也就是说，在 langgraph dev 这条服务链上，上层 graph 调用是 async-first，不是去调 graph.invoke()。

## 那为什么同步 node / tool 也能正常跑

因为 LangGraph 内部会把同步 callable 自动包装成可异步执行的 runnable。

核心证据在：
langgraph/_internal/_runnable.py (line 516)

这里逻辑是：

- 如果 callable 本身是 async，包装成 async runnable
- 如果 callable 是 sync，LangGraph 会给它补一个 async 版本。这个 async 版本内部是 run_in_executor(...)，也就是丢到线程池执行

所以你的 process_input()、同步 tool、同步 node，即使挂在一个异步执行的 graph 里，也照样能工作。

本质上是：

- 服务层：async 调 graph
- graph 内部：遇到 async node 就直接 await
- 遇到 sync node 就线程池桥接



# 关于memory

langgraph dev 在本地开发模式下，默认就是 inmem runtime，而且这个 runtime 不是“纯进程内、关掉就没”，而是默认会把 checkpoint/store 定期刷到 .langgraph_api/*.pckl 文件里。所以你看到这些文件，正是本地开发态短期记忆和运行数据落盘的结果。

证据链很明确：

langgraph_api.cli.run_server() 默认把 runtime_edition 设成 "inmem"，并写入环境变量 LANGGRAPH_RUNTIME_EDITION=inmem。cli.py (line 86)

langgraph_runtime 会根据这个环境变量加载 langgraph_runtime_inmem 作为实际后端。init.py (line 1)

这个 inmem runtime 里的 Checkpointer() 返回的是 InMemorySaver，但它的底层 PersistentDict 默认写到：

.langgraph_api/.langgraph_checkpoint.1.pckl
.langgraph_api/.langgraph_checkpoint.2.pckl
.langgraph_api/.langgraph_checkpoint.3.pckl
对应实现就在这里。checkpoint.py (line 1)

同样，默认 store 也是 DiskBackedInMemStore，会写：

.langgraph_api/store.pckl
.langgraph_api/store.vectors.pckl
对应实现这里。store.py (line 1)

而且它还有一个后台 flush 线程，每隔一段时间把内存里的内容 sync() 到这些文件，所以这些文件会持续增长。_persistence.py (line 1)

更关键的一点是：即使你自己的图里没有显式 .compile(checkpointer=...)，langgraph_api 在运行时也会把服务端拿到的 checkpointer 和 store 注入到 graph 上：

yield graph_obj.copy(update={"checkpointer": checkpointer, "store": store})

在这里。graph.py (line 184)

所以更准确的说法是：

- 对于 uv run langgraph dev 这条链路：有默认短期记忆，而且是本地 in-memory runtime + 文件落盘持久化
- 对于你自己在 Python 里直接 graph.invoke()：如果没显式传 checkpointer，那就不一定有这套能力
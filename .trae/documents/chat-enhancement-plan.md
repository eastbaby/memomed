# Memomed 聊天功能增强计划

## 项目背景
当前 Memomed 健康助手存在以下问题：
1. 大模型回答不能流式输出，用户体验不佳
2. 前端无法呈现 Markdown 格式，影响内容展示效果
3. 缺少一些常用的大模型对话框功能

## 实现目标
1. 实现大模型回答的流式输出
2. 前端支持 Markdown 格式渲染
3. 分析并实现常用的大模型对话框功能

## 详细任务列表

### [ ] 任务 1：后端实现流式输出
- **Priority**: P0
- **Depends On**: None
- **Description**:
  - 修改后端 `/chat` 接口，支持 Server-Sent Events (SSE) 流式输出
  - 启用 LangChain 的 streaming 模式
  - 实现流式数据的处理和传输
- **Success Criteria**:
  - 后端能够通过 SSE 流式返回大模型的回答
  - 前端能够接收并处理流式数据
- **Test Requirements**:
  - `programmatic` TR-1.1: 后端接口返回 Content-Type 为 text/event-stream
  - `programmatic` TR-1.2: 流式数据能够被前端正确接收和处理
  - `human-judgement` TR-1.3: 大模型回答能够实时显示，逐字输出

### [ ] 任务 2：前端实现 Next.js App Router 应用与 vercel/ai 集成
- **Priority**: P0
- **Depends On**: 任务 1
- **Description**:
  - 初始化 Next.js App Router 应用
  - 集成 vercel/ai 库
  - 实现基于 vercel/ai 的流式输出效果，遵循 vercel ai sdk  @use-ai-sdk 的技能规范
  - 配置基础的聊天界面
- **Success Criteria**:
  - 前端能够实时显示大模型的回答，逐字输出
  - 界面流畅，无卡顿现象
  - vercel/ai 库正确集成并工作
- **Test Requirements**:
  - `programmatic` TR-2.1: Next.js 应用成功构建和运行
  - `programmatic` TR-2.2: vercel/ai 库正确集成
  - `programmatic` TR-2.3: 流式数据能够实时更新到界面
  - `human-judgement` TR-2.4: 用户体验流畅，有打字机效果

### [ ] 任务 3：前端集成 Markdown 渲染
- **Priority**: P1
- **Depends On**: 任务 2
- **Description**:
  - 集成 Streamdown 或 Vercel AI SDK 内置的 Markdown 渲染功能
  - 确保 Markdown 样式美观，符合整体设计
  - 测试流式 Markdown 渲染效果
- **Success Criteria**:
  - 前端能够正确渲染 Markdown 格式的内容
  - 支持常见的 Markdown 语法，如标题、列表、链接等
  - 流式 Markdown 渲染正常工作
- **Test Requirements**:
  - `programmatic` TR-3.1: Markdown 渲染库正确集成
  - `programmatic` TR-3.2: 流式 Markdown 渲染正常工作
  - `human-judgement` TR-3.3: Markdown 内容渲染正确，样式美观

### [ ] 任务 4：利用 Vercel AI SDK 实现常用对话框功能
- **Priority**: P2
- **Depends On**: 任务 2
- **Description**:
  - 利用 Vercel AI SDK 的内置功能实现消息历史记录
  - 添加复制消息功能
  - 实现清空聊天记录功能
  - 添加消息时间戳
  - 配置对话状态管理
- **Success Criteria**:
  - 用户能够查看完整的聊天历史
  - 用户能够复制消息内容
  - 用户能够清空聊天记录
  - 消息显示包含时间戳
  - 对话状态管理正常工作
- **Test Requirements**:
  - `programmatic` TR-4.1: 消息历史记录功能正常
  - `programmatic` TR-4.2: 复制消息功能正常
  - `programmatic` TR-4.3: 对话状态管理正常
  - `human-judgement` TR-4.4: 界面设计美观，功能易用

### [ ] 任务 5：优化用户体验
- **Priority**: P2
- **Depends On**: 任务 2, 任务 3, 任务 4
- **Description**:
  - 优化 Next.js 应用的性能和加载速度
  - 实现错误处理和重试机制
  - 优化滚动行为，确保新消息自动滚动到可视区域
  - 添加响应式设计，适配不同设备
  - 优化 Vercel AI SDK 的使用体验
- **Success Criteria**:
  - 加载状态显示清晰
  - 错误处理机制完善
  - 滚动行为流畅
  - 在不同设备上显示正常
  - Next.js 应用性能良好
- **Test Requirements**:
  - `programmatic` TR-5.1: Next.js 应用性能优化
  - `human-judgement` TR-5.2: 加载状态显示清晰
  - `human-judgement` TR-5.3: 错误处理机制完善
  - `human-judgement` TR-5.4: 滚动行为流畅
  - `human-judgement` TR-5.5: 响应式设计良好

## 技术选型

### 后端
- **流式输出**: FastAPI + Server-Sent Events (SSE)
- **大模型**: LangChain + streaming=True

### 前端
- **框架**: Next.js App Router
- **AI 库**: Vercel AI SDK - 支持流式输出、对话状态管理等
- **Markdown 渲染**: Streamdown 或 Vercel AI SDK 内置的 Markdown 支持
- **UI 组件**: 自定义组件 + Tailwind CSS

## 实现步骤

1. **任务 1**: 修改后端代码，实现 SSE 流式输出
2. **任务 2**: 前端实现 Next.js App Router 应用与 Vercel AI SDK 集成
3. **任务 3**: 集成 Streamdown 或 Vercel AI SDK 内置的 Markdown 渲染
4. **任务 4**: 利用 Vercel AI SDK 的内置功能实现常用对话框功能
5. **任务 5**: 优化用户体验，添加额外功能

## 预期效果

1. **流式输出**: 用户发送消息后，大模型的回答会实时逐字显示，就像人类打字一样
2. **Markdown 支持**: 大模型返回的 Markdown 格式内容能够正确渲染，包括标题、列表、链接等
3. **功能丰富**: 对话框具备消息历史记录、复制功能、清空记录、时间戳等常用功能
4. **用户体验**: 界面美观，响应迅速，操作流畅

## 风险评估

1. **技术风险**: SSE 在某些环境下可能存在兼容性问题，需要测试不同浏览器
2. **性能风险**: 流式输出可能增加服务器负担，需要优化
3. **用户体验风险**: 流式输出速度需要适中，过快或过慢都会影响体验

## 测试计划

1. **功能测试**: 测试流式输出、Markdown 渲染、常用功能等
2. **性能测试**: 测试流式输出的响应速度和稳定性
3. **兼容性测试**: 测试不同浏览器的兼容性
4. **用户体验测试**: 评估整体用户体验

## 验收标准

1. 大模型回答能够流式输出，逐字显示
2. 前端能够正确渲染 Markdown 格式内容
3. 常用对话框功能正常工作
4. 用户体验流畅，界面美观
5. 系统稳定，无明显错误
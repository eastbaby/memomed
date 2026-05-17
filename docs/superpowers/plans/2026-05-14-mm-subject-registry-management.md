# Memomed 主体档案管理实现计划

> **给 agentic workers 的说明：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐步执行本计划。步骤使用 checkbox（`- [ ]`）语法，便于追踪进度。

**目标：** 做出第一版可用的家庭成员/宠物主体档案管理闭环：基于新的 `mm_` 表，提供后端 CRUD API 和一个简单前端管理页。

**架构：** Subject Registry 保持为普通 CRUD 模块，和 Agent Loop 分离。Agent 只读取 active 主体和别名作为 grounding 候选；人工修正、维护、新增则通过 `/api/subjects` 和前端主体管理页完成。

**技术栈：** FastAPI、SQLAlchemy async session、Pydantic v2、PostgreSQL/Alembic、React Vite、TypeScript、pnpm。

---

## 文件结构

- 创建 `backend/app/subjects/__init__.py`：subjects 包标记文件。
- 创建 `backend/app/subjects/schemas.py`：主体和别名的请求/响应模型。
- 创建 `backend/app/subjects/service.py`：别名标准化、查询、新增、更新、别名操作。
- 创建 `backend/app/subjects/routes.py`：挂载在 `/api/subjects` 下的 FastAPI 路由。
- 修改 `backend/app/main.py`：注册 subjects router。
- 创建 `backend/test/test_subject_registry.py`：测试 normalize 逻辑，以及在合适场景下用 mock session/service 测试 API 行为。
- 修改 `frontend/src/api/memomedAgentClient.ts`：增加通用 GET/PATCH helper 或 subjects API 函数。
- 创建 `frontend/src/types/subjects.ts`：前端主体和别名类型定义。
- 创建 `frontend/src/components/subjects/SubjectRegistryPage.tsx`：主体管理页，包含列表、新增表单、编辑表单、别名编辑器。
- 修改 `frontend/src/App.tsx`：增加 `聊天测试台` / `成员管理` 页面切换。
- 仅在页面需要少量复用样式时修改 `frontend/src/index.css`。

## 任务 1：后端主体 Schema

**文件：**
- 创建：`backend/app/subjects/__init__.py`
- 创建：`backend/app/subjects/schemas.py`

- [ ] **步骤 1：定义响应模型**

创建 Pydantic models：

```python
class SubjectAliasResponse(BaseModel):
    id: str
    alias: str
    normalized_alias: str
    source: str
    status: str
    created_at: datetime

class SubjectResponse(BaseModel):
    id: str
    owner_user_id: str
    subject_type: Literal["human", "pet"]
    display_name: str
    legal_name: str | None
    relation_type: str | None
    species: str | None
    breed: str | None
    gender: str | None
    birth_date: date | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
    aliases: list[SubjectAliasResponse]
```

- [ ] **步骤 2：定义新增/更新请求模型**

创建：

```python
class SubjectCreateRequest(BaseModel):
    subject_type: Literal["human", "pet"]
    display_name: str
    alias: str | None = None
    legal_name: str | None = None
    relation_type: str | None = None
    species: str | None = None
    breed: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    notes: str | None = None

class SubjectUpdateRequest(BaseModel):
    display_name: str | None = None
    legal_name: str | None = None
    relation_type: str | None = None
    species: str | None = None
    breed: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    status: Literal["active", "archived"] | None = None
    notes: str | None = None

class AliasCreateRequest(BaseModel):
    alias: str
    source: Literal["user", "ai", "system"] = "user"

class AliasUpdateRequest(BaseModel):
    alias: str | None = None
    status: Literal["active", "archived"] | None = None
```

## 任务 2：后端 Service 和 Routes

**文件：**
- 创建：`backend/app/subjects/service.py`
- 创建：`backend/app/subjects/routes.py`
- 修改：`backend/app/main.py`

- [ ] **步骤 1：实现 alias 标准化**

实现 `normalize_alias(alias: str) -> str`：

```python
normalized = unicodedata.normalize("NFKC", alias)
normalized = re.sub(r"\s+", " ", normalized.strip())
return normalized.casefold()
```

- [ ] **步骤 2：实现读取/新增/更新服务函数**

实现以下函数：

```python
async def list_subjects(owner_user_id: str = "default") -> list[SubjectResponse]
async def create_subject(payload: SubjectCreateRequest, owner_user_id: str = "default") -> SubjectResponse
async def update_subject(subject_id: UUID, payload: SubjectUpdateRequest, owner_user_id: str = "default") -> SubjectResponse
async def create_alias(subject_id: UUID, payload: AliasCreateRequest, owner_user_id: str = "default") -> SubjectResponse
async def update_alias(subject_id: UUID, alias_id: UUID, payload: AliasUpdateRequest, owner_user_id: str = "default") -> SubjectResponse
```

- [ ] **步骤 3：新增 FastAPI routes**

暴露以下接口：

```python
GET /api/subjects
POST /api/subjects
PATCH /api/subjects/{subject_id}
POST /api/subjects/{subject_id}/aliases
PATCH /api/subjects/{subject_id}/aliases/{alias_id}
```

- [ ] **步骤 4：在 app 中注册 router**

修改 `backend/app/main.py`：

```python
from app.subjects.routes import router as subjects_router

app.include_router(subjects_router)
```

## 任务 3：后端测试

**文件：**
- 创建：`backend/test/test_subject_registry.py`
- 仅当路由导入需要调整时，修改：`backend/test/test_agent_v1.py`

- [ ] **步骤 1：测试 normalize 逻辑**

验证：

```python
assert normalize_alias(" 我的  Cat ") == "我的 cat"
assert normalize_alias("ＡＢＣ") == "abc"
```

- [ ] **步骤 2：不依赖数据库测试 API 路由注册**

使用 FastAPI TestClient 断言 `/api/subjects` 存在。如果数据库不可用，patch service functions，而不是直接访问 PostgreSQL。

- [ ] **步骤 3：运行后端测试**

运行：

```bash
cd backend && uv run python -m unittest test.test_agent_v1 test.test_subject_registry
```

预期：所有测试通过。

## 任务 4：前端主体管理页

**文件：**
- 修改：`frontend/src/api/memomedAgentClient.ts`
- 创建：`frontend/src/types/subjects.ts`
- 创建：`frontend/src/components/subjects/SubjectRegistryPage.tsx`
- 修改：`frontend/src/App.tsx`

- [ ] **步骤 1：增加前端主体类型**

定义 `CareSubject`、`CareSubjectAlias`、新增/更新 payload 类型。

- [ ] **步骤 2：增加 API client 函数**

增加：

```ts
export function listSubjects()
export function createSubject(input)
export function updateSubject(subjectId, input)
export function createSubjectAlias(subjectId, input)
export function updateSubjectAlias(subjectId, aliasId, input)
```

- [ ] **步骤 3：构建 `SubjectRegistryPage`**

页面能力：

- 展示 active 和 archived 主体；
- 新增人物/宠物主体；
- 编辑展示名、关系、物种、品种、备注；
- 新增别名；
- 归档别名或主体。

- [ ] **步骤 4：增加应用内导航**

使用 React state：

```tsx
const [activePage, setActivePage] = useState<'chat' | 'subjects'>('chat')
```

不引入 router，只根据 state 渲染聊天页或主体管理页。

## 任务 5：验证

**文件：**
- 验证所有被修改的后端和前端文件。

- [ ] **步骤 1：运行后端测试**

```bash
cd backend && uv run python -m unittest test.test_agent_v1 test.test_subject_registry
```

- [ ] **步骤 2：运行后端编译检查**

```bash
cd backend && uv run python -m py_compile app/subjects/schemas.py app/subjects/service.py app/subjects/routes.py app/main.py
```

- [ ] **步骤 3：运行前端检查**

```bash
cd frontend && pnpm run build
cd frontend && pnpm run lint
```

- [ ] **步骤 4：手动浏览器冒烟测试**

打开 `http://127.0.0.1:3000/`，切换到 `成员管理`，验证即使后端不可用，页面也能渲染，并给出可理解的错误状态。

## 自检

- Spec 覆盖：本计划实现已确认的 `mm_` Subject Registry 管理层，并保持 Agent grounding 作为只读消费者。
- Placeholder 扫描：没有残留 `TBD` 或延后实现的模糊要求。
- 类型一致性：后端 subject/alias 命名匹配 `MmCareSubject` 和 `MmCareSubjectAlias`；前端使用 `CareSubject` 和 `CareSubjectAlias`。

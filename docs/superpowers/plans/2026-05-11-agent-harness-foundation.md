# Agent Harness Foundation 实施计划

> **给后续执行 Agent 的要求：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项执行。所有步骤使用 checkbox（`- [ ]`）追踪。

**目标：** 以企业级 Agent Harness 为核心重构 Memomed 后端 Agent 架构，建立标准请求、身份范围、意图路由、安全策略、工具注册、上下文组装、trace 元数据和 Harness-first LangGraph 主流程。旧代码只作为可迁移资产，不要求保持原有图结构。

**架构：** 新增 `backend/app/agent/harness/` 作为运行时控制层，并重写 `backend/app/agent/graph.py` 为 Harness-first graph。主流程先执行请求标准化、意图路由、策略判断和上下文组装，再分发到领域 workflow。现有报告上传、HITL、RAG、工具调用相关函数可以复用，但需要被重新组织到新的边界中。

**技术栈：** Python 3.12、Pydantic、LangGraph、LangChain tools、unittest、uv。

---

## 范围说明

已确认的 spec 覆盖 Harness、RAG、Memory、Tool Registry/MCP、HITL、Eval、部署和前端工作台。这个实施计划做第一阶段：**Agent Harness Foundation 重构**。它允许重写现有 Agent 图和节点边界，但不在本阶段完成 RAG schema、Memory 持久化或前端工作台。

本计划不做：

- PostgreSQL MCP 接入。
- 报告 OCR 可编辑 UI。
- `report_pages` 数据表。
- FTS/pgvector 混合检索改造。
- 长期记忆持久化重构。
- Review Inbox 持久化表。
- 前端 Health Workspace。

这些会在后续计划中单独推进。

---

## 文件结构

- 新增 `backend/app/agent/harness/__init__.py`：导出 Harness 公共类型和函数。
- 新增 `backend/app/agent/harness/types.py`：定义请求、身份范围、意图、安全策略、工具元信息、trace 等模型。
- 新增 `backend/app/agent/harness/request.py`：把用户输入和 LangGraph state 转成标准 `AgentRunRequest`。
- 新增 `backend/app/agent/harness/router.py`：确定性第一版意图路由。
- 新增 `backend/app/agent/harness/policy.py`：安全策略判断。
- 新增 `backend/app/agent/harness/tools.py`：工具注册元信息。
- 新增 `backend/app/agent/harness/context.py`：构造模型可读的 Harness 上下文。
- 新增 `backend/app/agent/harness/nodes.py`：LangGraph 节点 `prepare_harness_context`，作为新图的主入口治理节点。
- 新增 `backend/app/agent/workflows/__init__.py`：领域 workflow 包导出。
- 新增 `backend/app/agent/workflows/report_upload.py`：迁移报告上传、分组、元数据确认、入库相关节点和路由。
- 新增 `backend/app/agent/workflows/chat.py`：迁移模型调用、工具循环和回答生成节点。
- 修改 `backend/app/agent/utils/state.py`：给 `AgentState` 增加 Harness 字段。
- 修改 `backend/app/agent/utils/nodes.py`：只保留仍被共享的辅助函数；领域节点迁移到 `workflows/`。
- 重写 `backend/app/agent/graph.py`：以 Harness-first 方式重新组织主图。
- 新增 `backend/test/test_agent_harness.py`：Harness 单元测试。
- 修改 `backend/test/test_agent_async.py`：按新图行为重写 graph 集成测试。

---

## 任务 1：新增 Harness 核心类型

**文件：**

- 新增：`backend/app/agent/harness/__init__.py`
- 新增：`backend/app/agent/harness/types.py`
- 新增测试：`backend/test/test_agent_harness.py`

### 步骤

- [ ] **Step 1：先写失败测试**

创建 `backend/test/test_agent_harness.py`，覆盖以下行为：

```python
import unittest

from app.agent.harness.types import (
    AgentIntent,
    AgentRunRequest,
    PolicyAction,
    PolicyDecision,
    RiskTag,
    ToolRiskLevel,
    ToolSpec,
    TraceRecord,
)


class HarnessTypeTests(unittest.TestCase):
    def test_agent_run_request_has_safe_defaults(self) -> None:
        request = AgentRunRequest(
            run_id="run-1",
            thread_id="thread-1",
            user_text="帮我看看妈妈最近的体检报告",
        )

        self.assertEqual(request.input_channels, ["chat"])
        self.assertEqual(request.identity.user_id, "demo-user")
        self.assertIsNone(request.identity.patient_code)

    def test_policy_decision_serializes_risk_tags(self) -> None:
        decision = PolicyDecision(
            action=PolicyAction.REQUIRE_HITL,
            risk_tags=[RiskTag.PRESCRIPTION_CHANGE],
            reason="用药计划写操作必须确认",
        )

        dumped = decision.model_dump(mode="json")

        self.assertEqual(dumped["action"], "require_hitl")
        self.assertEqual(dumped["risk_tags"], ["prescription_change"])

    def test_tool_spec_marks_write_tools_as_high_risk(self) -> None:
        spec = ToolSpec(
            name="create_medication_reminder",
            description="创建用药提醒",
            risk_level=ToolRiskLevel.HIGH,
            read_or_write="write",
            allowed_intents=[AgentIntent.MEDICATION_MANAGEMENT],
            requires_hitl=True,
            audit_required=True,
            provider="internal_api",
        )

        self.assertTrue(spec.requires_hitl)
        self.assertTrue(spec.audit_required)

    def test_trace_record_keeps_policy_and_intent(self) -> None:
        trace = TraceRecord(
            run_id="run-1",
            thread_id="thread-1",
            intent=AgentIntent.REPORT_QA,
            policy_action=PolicyAction.ALLOW,
            selected_workflow="medical_report_qa",
        )

        self.assertEqual(trace.intent, AgentIntent.REPORT_QA)
        self.assertEqual(trace.policy_action, PolicyAction.ALLOW)
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessTypeTests -v
```

预期：失败，报 `ModuleNotFoundError: No module named 'app.agent.harness'`。

- [ ] **Step 3：实现 `types.py`**

新增 `backend/app/agent/harness/types.py`：

```python
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentIntent(str, Enum):
    REPORT_INGESTION = "report_ingestion"
    REPORT_QA = "report_qa"
    MEDICATION_MANAGEMENT = "medication_management"
    FOLLOWUP_PLANNING = "followup_planning"
    HEALTH_CONSULTATION = "health_consultation"
    SYSTEM_SETTINGS = "system_settings"
    GENERIC_CHAT = "generic_chat"


class RiskTag(str, Enum):
    MEDICAL_DIAGNOSIS = "medical_diagnosis"
    PRESCRIPTION_CHANGE = "prescription_change"
    EMERGENCY_SYMPTOM = "emergency_symptom"
    PRIVACY_SENSITIVE = "privacy_sensitive"
    FAMILY_SCOPE_AMBIGUITY = "family_scope_ambiguity"
    LOW_CONFIDENCE_EVIDENCE = "low_confidence_evidence"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


class PolicyAction(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_DISCLAIMER = "allow_with_disclaimer"
    ASK_CLARIFICATION = "ask_clarification"
    REQUIRE_HITL = "require_hitl"
    REFUSE = "refuse"
    ESCALATE_TO_DOCTOR = "escalate_to_doctor"


class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IdentityScope(BaseModel):
    user_id: str = "demo-user"
    family_workspace_id: str = "demo-family"
    patient_code: str | None = None
    patient_id: str | None = None
    allowed_patient_codes: list[str] = Field(default_factory=lambda: ["self", "mother", "father", "other"])


class AgentRunRequest(BaseModel):
    run_id: str
    thread_id: str
    user_text: str = ""
    input_channels: list[Literal["chat", "upload", "scheduled_task", "notification_callback"]] = Field(
        default_factory=lambda: ["chat"]
    )
    has_images: bool = False
    image_count: int = 0
    identity: IdentityScope = Field(default_factory=IdentityScope)
    raw_input: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    action: PolicyAction
    risk_tags: list[RiskTag] = Field(default_factory=list)
    reason: str
    disclaimer_required: bool = False


class ToolSpec(BaseModel):
    name: str
    description: str
    risk_level: ToolRiskLevel
    read_or_write: Literal["read", "write", "external_side_effect"]
    allowed_intents: list[AgentIntent]
    requires_hitl: bool = False
    audit_required: bool = True
    provider: Literal["internal_api", "mcp", "retriever", "utility"]
    timeout_seconds: int = 30
    retry_count: int = 0


class HarnessContext(BaseModel):
    request: AgentRunRequest
    intent: AgentIntent
    policy: PolicyDecision
    selected_workflow: str
    allowed_tools: list[str] = Field(default_factory=list)
    prompt_context: str = ""


class TraceRecord(BaseModel):
    run_id: str
    thread_id: str
    intent: AgentIntent
    policy_action: PolicyAction
    selected_workflow: str
    tool_calls: list[str] = Field(default_factory=list)
    risk_tags: list[RiskTag] = Field(default_factory=list)
```

- [ ] **Step 4：实现 `__init__.py` 导出**

新增 `backend/app/agent/harness/__init__.py`：

```python
from .types import (
    AgentIntent,
    AgentRunRequest,
    HarnessContext,
    IdentityScope,
    PolicyAction,
    PolicyDecision,
    RiskTag,
    ToolRiskLevel,
    ToolSpec,
    TraceRecord,
)

__all__ = [
    "AgentIntent",
    "AgentRunRequest",
    "HarnessContext",
    "IdentityScope",
    "PolicyAction",
    "PolicyDecision",
    "RiskTag",
    "ToolRiskLevel",
    "ToolSpec",
    "TraceRecord",
]
```

- [ ] **Step 5：运行测试确认通过**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessTypeTests -v
```

预期：全部通过。

- [ ] **Step 6：提交**

```bash
cd /Users/xinhuiwu/personalProj/memomed
git add backend/app/agent/harness/__init__.py backend/app/agent/harness/types.py backend/test/test_agent_harness.py
git commit -m "feat: add agent harness core types"
```

---

## 任务 2：请求标准化与意图路由

**文件：**

- 新增：`backend/app/agent/harness/request.py`
- 新增：`backend/app/agent/harness/router.py`
- 修改：`backend/app/agent/harness/__init__.py`
- 修改测试：`backend/test/test_agent_harness.py`

### 步骤

- [ ] **Step 1：补充失败测试**

在 `backend/test/test_agent_harness.py` 中追加：

```python
from app.agent.harness.request import build_agent_run_request
from app.agent.harness.router import route_intent


class HarnessRequestRouterTests(unittest.TestCase):
    def test_build_agent_run_request_extracts_text_and_images(self) -> None:
        state = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "帮妈妈存一下报告"},
                        {"type": "image", "mimeType": "image/png", "data": "abc"},
                    ],
                }
            ]
        }

        request = build_agent_run_request(state, thread_id="thread-1", run_id="run-1")

        self.assertEqual(request.user_text, "帮妈妈存一下报告")
        self.assertTrue(request.has_images)
        self.assertEqual(request.image_count, 1)
        self.assertEqual(request.identity.patient_code, "mother")

    def test_route_intent_report_ingestion_when_images_present(self) -> None:
        request = AgentRunRequest(
            run_id="run-1",
            thread_id="thread-1",
            user_text="帮妈妈存一下报告",
            has_images=True,
            image_count=1,
        )

        self.assertEqual(route_intent(request), AgentIntent.REPORT_INGESTION)

    def test_route_intent_medication_management(self) -> None:
        request = AgentRunRequest(
            run_id="run-1",
            thread_id="thread-1",
            user_text="提醒我爸每天早上吃降压药",
        )

        self.assertEqual(route_intent(request), AgentIntent.MEDICATION_MANAGEMENT)
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessRequestRouterTests -v
```

预期：失败，提示 `request` 或 `router` 模块不存在。

- [ ] **Step 3：实现请求标准化**

新增 `backend/app/agent/harness/request.py`：

```python
from __future__ import annotations

from typing import Any

from .types import AgentRunRequest, IdentityScope


def build_agent_run_request(
    state: dict[str, Any],
    *,
    thread_id: str = "unknown-thread",
    run_id: str = "unknown-run",
) -> AgentRunRequest:
    content = _latest_message_content(state)
    user_text = _flatten_text(content)
    image_count = _count_images(content)

    return AgentRunRequest(
        run_id=run_id,
        thread_id=thread_id,
        user_text=user_text,
        has_images=image_count > 0,
        image_count=image_count,
        identity=IdentityScope(patient_code=_infer_patient_code(user_text)),
        raw_input={"latest_content": content},
    )


def _latest_message_content(state: dict[str, Any]) -> Any:
    messages = state.get("messages") or []
    if not messages:
        return ""
    latest = messages[-1]
    if hasattr(latest, "content"):
        return latest.content
    if isinstance(latest, dict):
        return latest.get("content", "")
    return ""


def _flatten_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return str(content).strip() if content else ""


def _count_images(content: Any) -> int:
    if not isinstance(content, list):
        return 0
    return sum(1 for item in content if isinstance(item, dict) and item.get("type") in {"image", "image_url"})


def _infer_patient_code(text: str) -> str | None:
    if "妈妈" in text or "我妈" in text or "母亲" in text:
        return "mother"
    if "爸爸" in text or "我爸" in text or "父亲" in text:
        return "father"
    if text.startswith("我") or "我自己" in text or "我本人" in text:
        return "self"
    return None
```

- [ ] **Step 4：实现意图路由**

新增 `backend/app/agent/harness/router.py`：

```python
from __future__ import annotations

from .types import AgentIntent, AgentRunRequest


def route_intent(request: AgentRunRequest) -> AgentIntent:
    text = request.user_text.lower()

    if request.has_images and any(keyword in text for keyword in ["报告", "体检", "化验", "检查", "病历", "存"]):
        return AgentIntent.REPORT_INGESTION
    if any(keyword in text for keyword in ["吃药", "用药", "药", "剂量", "降压药", "提醒"]):
        return AgentIntent.MEDICATION_MANAGEMENT
    if any(keyword in text for keyword in ["复查", "随访", "下次检查", "检查时间"]):
        return AgentIntent.FOLLOWUP_PLANNING
    if any(keyword in text for keyword in ["报告", "指标", "异常", "检验", "化验", "肝功能", "血脂", "血糖"]):
        return AgentIntent.REPORT_QA
    if any(keyword in text for keyword in ["胸痛", "头晕", "发烧", "咳嗽", "不舒服", "症状"]):
        return AgentIntent.HEALTH_CONSULTATION
    if any(keyword in text for keyword in ["设置", "偏好", "记住", "以后"]):
        return AgentIntent.SYSTEM_SETTINGS
    return AgentIntent.GENERIC_CHAT
```

- [ ] **Step 5：更新导出**

在 `backend/app/agent/harness/__init__.py` 中加入：

```python
from .request import build_agent_run_request
from .router import route_intent
```

并把 `build_agent_run_request`、`route_intent` 加入 `__all__`。

- [ ] **Step 6：运行测试确认通过**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessRequestRouterTests -v
```

预期：全部通过。

- [ ] **Step 7：提交**

```bash
cd /Users/xinhuiwu/personalProj/memomed
git add backend/app/agent/harness/__init__.py backend/app/agent/harness/request.py backend/app/agent/harness/router.py backend/test/test_agent_harness.py
git commit -m "feat: normalize agent requests and route intents"
```

---

## 任务 3：安全策略与工具注册

**文件：**

- 新增：`backend/app/agent/harness/policy.py`
- 新增：`backend/app/agent/harness/tools.py`
- 修改：`backend/app/agent/harness/__init__.py`
- 修改测试：`backend/test/test_agent_harness.py`

### 步骤

- [ ] **Step 1：补充失败测试**

在 `backend/test/test_agent_harness.py` 中追加：

```python
from app.agent.harness.policy import evaluate_policy
from app.agent.harness.tools import get_allowed_tool_names, get_tool_registry


class HarnessPolicyToolTests(unittest.TestCase):
    def test_policy_escalates_emergency_symptoms(self) -> None:
        request = AgentRunRequest(
            run_id="run-1",
            thread_id="thread-1",
            user_text="我胸口很痛但不想去医院",
        )

        decision = evaluate_policy(request, AgentIntent.HEALTH_CONSULTATION)

        self.assertEqual(decision.action, PolicyAction.ESCALATE_TO_DOCTOR)
        self.assertIn(RiskTag.EMERGENCY_SYMPTOM, decision.risk_tags)

    def test_policy_requires_hitl_for_medication_write(self) -> None:
        request = AgentRunRequest(
            run_id="run-1",
            thread_id="thread-1",
            user_text="帮我爸设置每天早上吃一片降压药提醒",
        )

        decision = evaluate_policy(request, AgentIntent.MEDICATION_MANAGEMENT)

        self.assertEqual(decision.action, PolicyAction.REQUIRE_HITL)
        self.assertIn(RiskTag.PRESCRIPTION_CHANGE, decision.risk_tags)

    def test_tool_registry_filters_by_intent(self) -> None:
        registry = get_tool_registry()
        tool_names = [tool.name for tool in registry]

        self.assertIn("search_medical_reports", tool_names)
        self.assertIn("get_current_time", tool_names)

        report_tools = get_allowed_tool_names(AgentIntent.REPORT_QA)
        medication_tools = get_allowed_tool_names(AgentIntent.MEDICATION_MANAGEMENT)

        self.assertIn("search_medical_reports", report_tools)
        self.assertIn("get_current_time", medication_tools)
        self.assertNotIn("calculate", medication_tools)
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessPolicyToolTests -v
```

预期：失败，提示 `policy` 或 `tools` 模块不存在。

- [ ] **Step 3：实现安全策略**

新增 `backend/app/agent/harness/policy.py`：

```python
from __future__ import annotations

from .types import AgentIntent, AgentRunRequest, PolicyAction, PolicyDecision, RiskTag


def evaluate_policy(request: AgentRunRequest, intent: AgentIntent) -> PolicyDecision:
    text = request.user_text

    if _contains_emergency_symptom(text):
        return PolicyDecision(
            action=PolicyAction.ESCALATE_TO_DOCTOR,
            risk_tags=[RiskTag.EMERGENCY_SYMPTOM],
            reason="用户描述可能涉及急症，应提示及时就医或急救。",
            disclaimer_required=True,
        )

    if intent == AgentIntent.MEDICATION_MANAGEMENT:
        return PolicyDecision(
            action=PolicyAction.REQUIRE_HITL,
            risk_tags=[RiskTag.PRESCRIPTION_CHANGE],
            reason="用药计划、剂量、频率或提醒写入必须经过用户确认。",
            disclaimer_required=True,
        )

    if intent in {AgentIntent.REPORT_QA, AgentIntent.HEALTH_CONSULTATION}:
        return PolicyDecision(
            action=PolicyAction.ALLOW_WITH_DISCLAIMER,
            risk_tags=[],
            reason="健康解释类问题允许回答，但必须说明不能替代医生诊断。",
            disclaimer_required=True,
        )

    return PolicyDecision(action=PolicyAction.ALLOW, risk_tags=[], reason="低风险请求允许继续。")


def _contains_emergency_symptom(text: str) -> bool:
    emergency_keywords = ["胸口很痛", "胸痛", "呼吸困难", "昏迷", "意识不清", "大出血", "中风", "心梗"]
    return any(keyword in text for keyword in emergency_keywords)
```

- [ ] **Step 4：实现工具注册**

新增 `backend/app/agent/harness/tools.py`：

```python
from __future__ import annotations

from .types import AgentIntent, ToolRiskLevel, ToolSpec


def get_tool_registry() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="get_current_time",
            description="获取当前时间，用于提醒和复查时间解释。",
            risk_level=ToolRiskLevel.LOW,
            read_or_write="read",
            allowed_intents=[AgentIntent.MEDICATION_MANAGEMENT, AgentIntent.FOLLOWUP_PLANNING, AgentIntent.GENERIC_CHAT],
            requires_hitl=False,
            audit_required=False,
            provider="utility",
        ),
        ToolSpec(
            name="calculate",
            description="执行简单数学计算。",
            risk_level=ToolRiskLevel.LOW,
            read_or_write="read",
            allowed_intents=[AgentIntent.GENERIC_CHAT],
            requires_hitl=False,
            audit_required=False,
            provider="utility",
        ),
        ToolSpec(
            name="search_medical_reports",
            description="只读搜索用户已入库的医疗报告片段。",
            risk_level=ToolRiskLevel.LOW,
            read_or_write="read",
            allowed_intents=[AgentIntent.REPORT_QA, AgentIntent.HEALTH_CONSULTATION],
            requires_hitl=False,
            audit_required=True,
            provider="retriever",
        ),
    ]


def get_allowed_tool_names(intent: AgentIntent) -> list[str]:
    return [tool.name for tool in get_tool_registry() if intent in tool.allowed_intents]
```

- [ ] **Step 5：更新导出**

在 `backend/app/agent/harness/__init__.py` 中加入：

```python
from .policy import evaluate_policy
from .tools import get_allowed_tool_names, get_tool_registry
```

并把三个名称加入 `__all__`。

- [ ] **Step 6：运行测试确认通过**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessPolicyToolTests -v
```

预期：全部通过。

- [ ] **Step 7：提交**

```bash
cd /Users/xinhuiwu/personalProj/memomed
git add backend/app/agent/harness/__init__.py backend/app/agent/harness/policy.py backend/app/agent/harness/tools.py backend/test/test_agent_harness.py
git commit -m "feat: add harness policy and tool registry"
```

---

## 任务 4：构造 Harness Context 节点并迁移领域 Workflow

**文件：**

- 新增：`backend/app/agent/harness/context.py`
- 新增：`backend/app/agent/harness/nodes.py`
- 新增：`backend/app/agent/workflows/__init__.py`
- 新增：`backend/app/agent/workflows/report_upload.py`
- 新增：`backend/app/agent/workflows/chat.py`
- 修改：`backend/app/agent/harness/__init__.py`
- 修改：`backend/app/agent/utils/state.py`
- 修改测试：`backend/test/test_agent_harness.py`

### 步骤

- [ ] **Step 1：补充失败测试**

在 `backend/test/test_agent_harness.py` 中追加：

```python
from app.agent.harness.context import build_harness_context
from app.agent.harness.nodes import prepare_harness_context


class HarnessContextNodeTests(unittest.IsolatedAsyncioTestCase):
    def test_build_harness_context_selects_workflow_and_tools(self) -> None:
        request = AgentRunRequest(
            run_id="run-1",
            thread_id="thread-1",
            user_text="妈妈肝功能报告里 ALT 高是什么意思",
        )
        intent = AgentIntent.REPORT_QA
        policy = evaluate_policy(request, intent)

        context = build_harness_context(request, intent, policy)

        self.assertEqual(context.selected_workflow, "medical_report_qa")
        self.assertIn("search_medical_reports", context.allowed_tools)
        self.assertIn("意图：report_qa", context.prompt_context)

    async def test_prepare_harness_context_returns_serializable_state(self) -> None:
        state = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "提醒我爸每天早上吃降压药"}],
                }
            ]
        }

        result = await prepare_harness_context(state)

        self.assertEqual(result["harness_intent"], "medication_management")
        self.assertEqual(result["harness_policy"]["action"], "require_hitl")
        self.assertIn("get_current_time", result["allowed_tool_names"])
        self.assertIn("harness_trace", result)
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessContextNodeTests -v
```

预期：失败，提示 `context` 或 `nodes` 模块不存在。

- [ ] **Step 3：实现 `context.py`**

新增 `backend/app/agent/harness/context.py`：

```python
from __future__ import annotations

from .tools import get_allowed_tool_names
from .types import AgentIntent, AgentRunRequest, HarnessContext, PolicyDecision


WORKFLOW_BY_INTENT: dict[AgentIntent, str] = {
    AgentIntent.REPORT_INGESTION: "report_ingestion",
    AgentIntent.REPORT_QA: "medical_report_qa",
    AgentIntent.MEDICATION_MANAGEMENT: "medication_management",
    AgentIntent.FOLLOWUP_PLANNING: "followup_planning",
    AgentIntent.HEALTH_CONSULTATION: "health_consultation",
    AgentIntent.SYSTEM_SETTINGS: "system_settings",
    AgentIntent.GENERIC_CHAT: "generic_chat",
}


def build_harness_context(
    request: AgentRunRequest,
    intent: AgentIntent,
    policy: PolicyDecision,
) -> HarnessContext:
    allowed_tools = get_allowed_tool_names(intent)
    selected_workflow = WORKFLOW_BY_INTENT[intent]
    prompt_context = "\n".join(
        [
            "Agent Harness Context:",
            f"- run_id：{request.run_id}",
            f"- thread_id：{request.thread_id}",
            f"- 患者范围：{request.identity.patient_code or '未指定'}",
            f"- 意图：{intent.value}",
            f"- 策略：{policy.action.value}",
            f"- 策略原因：{policy.reason}",
            f"- 选中工作流：{selected_workflow}",
            f"- 允许工具：{'、'.join(allowed_tools) if allowed_tools else '无'}",
        ]
    )

    return HarnessContext(
        request=request,
        intent=intent,
        policy=policy,
        selected_workflow=selected_workflow,
        allowed_tools=allowed_tools,
        prompt_context=prompt_context,
    )
```

- [ ] **Step 4：实现 `nodes.py`**

新增 `backend/app/agent/harness/nodes.py`：

```python
from __future__ import annotations

from typing import Any
from uuid import uuid4

from .context import build_harness_context
from .policy import evaluate_policy
from .request import build_agent_run_request
from .router import route_intent
from .types import TraceRecord


async def prepare_harness_context(state: dict[str, Any]) -> dict[str, Any]:
    request = build_agent_run_request(state, thread_id="unknown-thread", run_id=str(uuid4()))
    intent = route_intent(request)
    policy = evaluate_policy(request, intent)
    context = build_harness_context(request, intent, policy)
    trace = TraceRecord(
        run_id=request.run_id,
        thread_id=request.thread_id,
        intent=intent,
        policy_action=policy.action,
        selected_workflow=context.selected_workflow,
        risk_tags=policy.risk_tags,
    )

    return {
        "harness_context": context.prompt_context,
        "harness_intent": intent.value,
        "harness_policy": policy.model_dump(mode="json"),
        "selected_workflow": context.selected_workflow,
        "allowed_tool_names": context.allowed_tools,
        "harness_trace": trace.model_dump(mode="json"),
    }
```

- [ ] **Step 5：扩展 `AgentState`**

修改 `backend/app/agent/utils/state.py`，把 state 明确整理成三组字段：消息输入、报告上传工作流、Harness 元数据。最终文件应为：

```python
from typing import Annotated, Literal
from typing_extensions import TypedDict
import operator


class AgentState(TypedDict):
    # LangGraph messages reducer
    messages: Annotated[list, operator.add]

    # 输入与报告上传 workflow 状态
    question_message_content: list
    human_image_list: list
    human_image_store_list: list[Literal["store_success", "store_failed", "store_pending", "no_store"]]
    report_upload_plans: list[dict]

    # Agent Harness 状态
    harness_context: str
    harness_intent: str
    harness_policy: dict
    selected_workflow: str
    allowed_tool_names: list[str]
    harness_trace: dict

    # 模型输出状态
    answer_keypoints: list[str]
    response: str
    metadata: dict
```

- [ ] **Step 6：迁移报告上传 workflow 节点**

新建 `backend/app/agent/workflows/report_upload.py`，先从 `backend/app/agent/utils/nodes.py` 移动这些报告上传相关内容：

```python
process_input
route_after_process_input
confirm_report_uploads
route_after_confirm_report_uploads
prepare_report_uploads
route_after_prepare_report_uploads
notify_metadata_confirmation
confirm_report_metadata
route_after_confirm_report_metadata
finalize_report_uploads
HumanImageStoreItem
HumanImageStoreList
ReportImageFeature
ReportUploadGroup
ReportUploadAnalysis
```

同时移动这些私有辅助函数：

```python
_extract_conversation_context
_decide_whether_store_image
_plan_report_uploads
_build_report_upload_interrupt_payload
_apply_report_upload_confirmation
_plan_requires_metadata_confirmation
_build_metadata_interrupt_payload
_apply_metadata_confirmation
_collect_plan_image_urls
_build_image_store_status_message
```

移动后，`report_upload.py` 的 import 应只包含自己实际需要的依赖：

```python
import copy
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError

from app.agent.utils.llm import get_openai_llm_non_stream
from app.agent.utils.state import AgentState
from app.agent.utils.hitl import (
    HITLRequest,
    HITLActionRequest,
    HITLReviewConfig,
    HITLResumePayload,
)
from app.agent.utils.rag import ReportMetadata, prepare_medical_report, store_prepared_medical_report
```

- [ ] **Step 7：迁移 chat/tool workflow 节点**

新建 `backend/app/agent/workflows/chat.py`，从 `backend/app/agent/utils/nodes.py` 移动这些模型与工具循环相关内容：

```python
call_model
tools_condition
generate_response
MedicalAgentTask
tool_node
_extract_answer_keypoints
_get_latest_user_question
_flatten_content_to_text
```

`call_model` 必须在迁移时接入 Harness：

```python
allowed_tool_names = set(state.get("allowed_tool_names") or [])
tools = [
    tool
    for tool in get_tools()
    if not allowed_tool_names or getattr(tool, "name", None) in allowed_tool_names
]
harness_context = state.get("harness_context") or "无"
```

system prompt 中必须包含：

```text
Agent Harness：
{harness_context}
```

- [ ] **Step 8：保留兼容 re-export**

为了减少一次性改动风险，把 `backend/app/agent/utils/nodes.py` 改成兼容导出文件，内容为：

```python
from app.agent.workflows.chat import (
    call_model,
    generate_response,
    tool_node,
    tools_condition,
)
from app.agent.workflows.report_upload import (
    confirm_report_metadata,
    confirm_report_uploads,
    finalize_report_uploads,
    notify_metadata_confirmation,
    prepare_report_uploads,
    process_input,
    route_after_confirm_report_metadata,
    route_after_confirm_report_uploads,
    route_after_prepare_report_uploads,
    route_after_process_input,
)

__all__ = [
    "call_model",
    "confirm_report_metadata",
    "confirm_report_uploads",
    "finalize_report_uploads",
    "generate_response",
    "notify_metadata_confirmation",
    "prepare_report_uploads",
    "process_input",
    "route_after_confirm_report_metadata",
    "route_after_confirm_report_uploads",
    "route_after_prepare_report_uploads",
    "route_after_process_input",
    "tool_node",
    "tools_condition",
]
```

这个文件只是临时兼容层，后续计划可以删除。

- [ ] **Step 9：新增 workflow 包导出**

新增 `backend/app/agent/workflows/__init__.py`：

```python
"""Domain workflows used by the Memomed LangGraph agent."""
```

- [ ] **Step 10：更新导出**

在 `backend/app/agent/harness/__init__.py` 中加入：

```python
from .context import build_harness_context
from .nodes import prepare_harness_context
```

并加入 `__all__`。

- [ ] **Step 11：运行测试确认通过**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessContextNodeTests -v
```

预期：全部通过。

- [ ] **Step 12：提交**

```bash
cd /Users/xinhuiwu/personalProj/memomed
git add backend/app/agent/harness/__init__.py backend/app/agent/harness/context.py backend/app/agent/harness/nodes.py backend/app/agent/workflows backend/app/agent/utils/state.py backend/app/agent/utils/nodes.py backend/test/test_agent_harness.py
git commit -m "feat: split agent workflows behind harness"
```

---

## 任务 5：重写 Harness-first LangGraph 主流程

**文件：**

- 修改：`backend/app/agent/graph.py`
- 修改测试：`backend/test/test_agent_harness.py`
- 必要时修改：`backend/test/test_agent_async.py`

### 步骤

- [ ] **Step 1：补充 graph 集成测试**

在 `backend/test/test_agent_harness.py` 中追加：

```python
from langchain_core.messages import AIMessage
from unittest.mock import AsyncMock, patch

from app.agent.graph import graph
from app.agent.workflows import report_upload
from app.agent.workflows import chat


class HarnessGraphIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_adds_harness_state_for_plain_chat(self) -> None:
        state = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "妈妈肝功能报告里 ALT 高是什么意思"}],
                }
            ]
        }
        config = {"configurable": {"thread_id": "harness-thread"}}

        class _FakeBoundLLM:
            async def ainvoke(self, messages):
                self.seen_system_prompt = messages[0]["content"]
                return AIMessage(content="ALT 是肝功能相关指标，建议结合医生意见。")

        fake_bound = _FakeBoundLLM()

        class _FakeLLM:
            def bind_tools(self, tool_list):
                return fake_bound

        with (
            patch.object(report_upload, "_decide_whether_store_image", new=AsyncMock(return_value=[])),
            patch.object(chat, "get_openai_llm_stream", return_value=_FakeLLM()),
            patch.object(chat, "_extract_answer_keypoints", new=AsyncMock(return_value=[])),
        ):
            result = await graph.ainvoke(state, config)

        self.assertEqual(result["harness_intent"], "report_qa")
        self.assertEqual(result["selected_workflow"], "medical_report_qa")
        self.assertIn("Agent Harness Context", result["harness_context"])
        self.assertIn("意图：report_qa", fake_bound.seen_system_prompt)
        self.assertEqual(result["response"], "ALT 是肝功能相关指标，建议结合医生意见。")
```

- [ ] **Step 2：运行测试确认失败**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessGraphIntegrationTests -v
```

预期：失败，因为主图还没有按 Harness-first 方式重写。

- [ ] **Step 3：重写 `graph.py`**

把 `backend/app/agent/graph.py` 重写为：

```python
from langgraph.graph import END, START, StateGraph

from app.agent.harness.nodes import prepare_harness_context
from app.agent.utils.state import AgentState
from app.agent.workflows.chat import (
    call_model,
    generate_response,
    tool_node,
    tools_condition,
)
from app.agent.workflows.report_upload import (
    confirm_report_metadata,
    confirm_report_uploads,
    finalize_report_uploads,
    notify_metadata_confirmation,
    prepare_report_uploads,
    process_input,
    route_after_confirm_report_metadata,
    route_after_confirm_report_uploads,
    route_after_prepare_report_uploads,
    route_after_process_input,
)


graph = (
    StateGraph(AgentState)
    .add_node("process_input", process_input)
    .add_node("prepare_harness_context", prepare_harness_context)
    .add_node("confirm_report_uploads", confirm_report_uploads)
    .add_node("prepare_report_uploads", prepare_report_uploads)
    .add_node("notify_metadata_confirmation", notify_metadata_confirmation)
    .add_node("confirm_report_metadata", confirm_report_metadata)
    .add_node("finalize_report_uploads", finalize_report_uploads)
    .add_node("call_model", call_model)
    .add_node("tools", tool_node)
    .add_node("generate_response", generate_response)
    .add_edge(START, "process_input")
    .add_edge("process_input", "prepare_harness_context")
    .add_conditional_edges(
        "prepare_harness_context",
        route_after_process_input,
        {
            "confirm_report_uploads": "confirm_report_uploads",
            "prepare_report_uploads": "prepare_report_uploads",
            "call_model": "call_model",
        },
    )
    .add_conditional_edges(
        "confirm_report_uploads",
        route_after_confirm_report_uploads,
        {
            "prepare_report_uploads": "prepare_report_uploads",
            "call_model": "call_model",
        },
    )
    .add_conditional_edges(
        "prepare_report_uploads",
        route_after_prepare_report_uploads,
        {
            "notify_metadata_confirmation": "notify_metadata_confirmation",
            "finalize_report_uploads": "finalize_report_uploads",
        },
    )
    .add_edge("notify_metadata_confirmation", "confirm_report_metadata")
    .add_conditional_edges(
        "confirm_report_metadata",
        route_after_confirm_report_metadata,
        {
            "finalize_report_uploads": "finalize_report_uploads",
            "call_model": "call_model",
        },
    )
    .add_edge("finalize_report_uploads", "call_model")
    .add_conditional_edges("call_model", tools_condition, {"tools": "tools", "end": "generate_response"})
    .add_edge("tools", "call_model")
    .add_edge("generate_response", END)
    .compile(name="memomed_agent")
)
```

目标链路：

```text
START
→ process_input
→ prepare_harness_context
→ 根据 report_upload_plans 分流到报告 workflow 或 call_model
```

- [ ] **Step 4：运行集成测试**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness.HarnessGraphIntegrationTests -v
```

预期：全部通过。

- [ ] **Step 5：重写并运行图集成测试**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_async.NodeFlowTests -v
```

预期：全部通过。测试应断言新图行为，而不是旧图结构。至少保留这些行为：

- 单图报告可完成入库并进入模型回复。
- 多图报告会触发上传确认 interrupt。
- 元数据不确定时会触发元数据确认 interrupt。
- 普通报告问答会生成 `harness_intent=report_qa`。

- [ ] **Step 6：提交**

```bash
cd /Users/xinhuiwu/personalProj/memomed
git add backend/app/agent/graph.py backend/test/test_agent_harness.py backend/test/test_agent_async.py
git commit -m "feat: rebuild agent graph around harness"
```

---

## 任务 6：更新官方 Graph 图并完整验证

**文件：**

- 修改生成物：`docs/diagrams/memomed-langgraph-official.mmd`
- 修改生成物：`docs/diagrams/memomed-langgraph-official.png`
- 修改生成物：`docs/diagrams/memomed-langgraph-official.md`

### 步骤

- [ ] **Step 1：重新生成官方图**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python test/export_langgraph_diagram.py
```

预期输出：

```text
Mermaid: ../docs/diagrams/memomed-langgraph-official.mmd
PNG: ../docs/diagrams/memomed-langgraph-official.png
Markdown: ../docs/diagrams/memomed-langgraph-official.md
```

- [ ] **Step 2：确认图里包含 Harness 节点**

```bash
cd /Users/xinhuiwu/personalProj/memomed
rg "prepare_harness_context" docs/diagrams/memomed-langgraph-official.mmd docs/diagrams/memomed-langgraph-official.md
```

预期：两个文件都能搜到 `prepare_harness_context`。

- [ ] **Step 3：运行全部相关测试**

```bash
cd /Users/xinhuiwu/personalProj/memomed/backend
uv run python -m unittest test.test_agent_harness test.test_agent_async -v
```

预期：全部通过。

- [ ] **Step 4：检查 diff**

```bash
cd /Users/xinhuiwu/personalProj/memomed
git diff --check
```

预期：无输出。

- [ ] **Step 5：提交图更新**

```bash
cd /Users/xinhuiwu/personalProj/memomed
git add docs/diagrams/memomed-langgraph-official.mmd docs/diagrams/memomed-langgraph-official.png docs/diagrams/memomed-langgraph-official.md
git commit -m "docs: update graph diagram for harness node"
```

---

## 自检

覆盖情况：

- Harness 运行时类型：任务 1。
- 请求标准化和 patient hint 提取：任务 2。
- 意图路由：任务 2。
- 安全策略：任务 3。
- 工具注册元信息：任务 3。
- Context Builder：任务 4。
- LangGraph 接入：任务 5。
- Trace 元数据：任务 4。
- 官方图更新：任务 6。

延期内容：

- RAG schema 和混合检索：后续单独计划。
- Memory Manager 持久化和后台整理：后续单独计划。
- Review Inbox 和前端工作台：后续单独计划。
- MCP 接入：等 Tool Registry 元信息落地后再做。

一致性检查：

- `AgentIntent`、`PolicyAction`、`RiskTag`、`ToolRiskLevel`、`ToolSpec`、`AgentRunRequest`、`HarnessContext`、`TraceRecord` 在任务 1 中定义，后续任务沿用同一套名称。
- `prepare_harness_context` 返回的字段全部加入 `AgentState`。
- `allowed_tool_names` 在 state 中是 `list[str]`，在 `call_model` 中用于过滤工具。

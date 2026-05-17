# Memomed Agent Clean Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把旧 `backend/app/agent/` 备份起来，在正式 `app/agent/` 目录重写一个最小 Agent Loop，并提供一个自定义前端页面测试 `select_one interrupt -> resume -> 强制续接`。

**Architecture:** 后端保留 `app.agent.graph:graph` 作为 LangGraph 正式入口，新增 runtime 和 FastAPI routes 封装 `start_chat` / `resume_chat`。前端整体备份旧 Next.js 实现后，使用普通 React + Vite 重建一个自定义 Agent 测试台，直接调用后端 `/api/agent/chat` 和 `/api/agent/resume`。

**Tech Stack:** Python 3.12, FastAPI, LangGraph, LangChain tools, Pydantic, React, Vite, TypeScript, Tailwind CSS.

---

## File Structure

### Backend legacy backup

- Move: `backend/app/agent/` -> `backend/app/agent_legacy_backup/`
- Create: `backend/app/agent_legacy_backup/README.md`

`agent_legacy_backup` 只作为参考代码，不被新代码 import。

### Backend new agent

- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/state.py`
- Create: `backend/app/agent/prompts.py`
- Create: `backend/app/agent/graph.py`
- Create: `backend/app/agent/runtime.py`
- Create: `backend/app/agent/tools/__init__.py`
- Create: `backend/app/agent/tools/schemas.py`
- Create: `backend/app/agent/tools/patient.py`
- Create: `backend/app/agent/tools/registry.py`
- Create: `backend/app/agent/hitl/__init__.py`
- Create: `backend/app/agent/hitl/schemas.py`
- Create: `backend/app/agent/hitl/router.py`
- Create: `backend/app/agent/api/__init__.py`
- Create: `backend/app/agent/api/schemas.py`
- Create: `backend/app/agent/api/routes.py`
- Modify: `backend/app/main.py`

### Backend tests

- Create: `backend/test/test_agent_v1.py`

### Frontend legacy backup and Vite rebuild

- Move: `frontend/` -> `frontend_legacy_backup/`
- Create: `frontend/package.json`
- Create: `frontend/eslint.config.js`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/types/agent.ts`
- Create: `frontend/src/api/memomedAgentClient.ts`
- Create: `frontend/src/components/agent/ChatTimeline.tsx`
- Create: `frontend/src/components/agent/ProcessEventCard.tsx`
- Create: `frontend/src/components/agent/InterruptCard.tsx`
- Create: `frontend/src/components/agent/SelectOneCard.tsx`
- Create: `frontend/src/components/agent/ConfirmCard.tsx`
- Create: `frontend/src/components/agent/TextInputCard.tsx`
- Create: `frontend/src/components/agent/Composer.tsx`

---

## Task 1: Backup Legacy Agent And Create Empty New Agent Shell

**Files:**
- Move: `backend/app/agent/` -> `backend/app/agent_legacy_backup/`
- Create: `backend/app/agent_legacy_backup/README.md`
- Create: `backend/app/agent/__init__.py`

- [ ] **Step 1: Move the legacy directory**

Run:

```bash
mv backend/app/agent backend/app/agent_legacy_backup
mkdir -p backend/app/agent
touch backend/app/agent/__init__.py
```

Expected: `backend/app/agent_legacy_backup/graph.py` exists and `backend/app/agent/__init__.py` exists.

- [ ] **Step 2: Add backup README**

Create `backend/app/agent_legacy_backup/README.md`:

```markdown
# Legacy Agent Backup

This directory contains the previous Memomed agent implementation.

It is kept only as reference material while the new `app.agent` implementation is rebuilt from a clean Agent Loop + HITL runtime.

Runtime code must not import from `app.agent_legacy_backup`.
```

- [ ] **Step 3: Verify imports fail early if graph is missing**

Run:

```bash
cd backend
uv run python -c "import app.agent; print('agent shell ok')"
```

Expected: prints `agent shell ok`.

- [ ] **Step 4: Commit**

Run:

```bash
git add backend/app/agent backend/app/agent_legacy_backup
git commit -m "refactor: backup legacy agent"
```

---

## Task 2: Define Shared Agent And HITL Schemas

**Files:**
- Create: `backend/app/agent/tools/schemas.py`
- Create: `backend/app/agent/hitl/schemas.py`
- Create: `backend/app/agent/state.py`
- Test: `backend/test/test_agent_v1.py`

- [ ] **Step 1: Write failing schema tests**

Create `backend/test/test_agent_v1.py`:

```python
import unittest

from app.agent.hitl.schemas import InteractionRequest, SelectOption
from app.agent.tools.schemas import PendingAction, ToolResult


class AgentV1SchemaTests(unittest.TestCase):
    def test_tool_result_requires_pending_action_for_selection(self) -> None:
        result = ToolResult(
            status="needs_user_selection",
            message="需要确认人物",
            pending_action=PendingAction(
                id="pa_001",
                type="confirm_patient",
                continuation_tool="commit_patient_selection",
                candidate_payload={"original_text": "帮家人存一下这个报告"},
            ),
            interaction=InteractionRequest(
                type="select_one",
                title="这次要管理谁的健康档案？",
                options=[SelectOption(label="妈妈", value="mother")],
            ),
        )

        self.assertEqual(result.status, "needs_user_selection")
        self.assertEqual(result.pending_action.continuation_tool, "commit_patient_selection")
        self.assertEqual(result.interaction.options[0].value, "mother")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1.AgentV1SchemaTests.test_tool_result_requires_pending_action_for_selection
```

Expected: FAIL or ERROR because `app.agent.hitl.schemas` / `app.agent.tools.schemas` do not exist.

- [ ] **Step 3: Implement HITL schemas**

Create `backend/app/agent/hitl/__init__.py` as an empty file.

Create `backend/app/agent/hitl/schemas.py`:

```python
from typing import Any, Literal

from pydantic import BaseModel, Field


class SelectOption(BaseModel):
    label: str
    value: str


class InteractionRequest(BaseModel):
    type: Literal["select_one", "confirm", "text_input"]
    title: str
    description: str | None = None
    options: list[SelectOption] = Field(default_factory=list)
    placeholder: str | None = None
    pending_action: dict[str, Any] | None = None
```

- [ ] **Step 4: Implement tool schemas**

Create `backend/app/agent/tools/__init__.py` as an empty file.

Create `backend/app/agent/tools/schemas.py`:

```python
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from app.agent.hitl.schemas import InteractionRequest


ToolStatus = Literal[
    "success",
    "needs_user_confirmation",
    "needs_user_selection",
    "needs_user_input",
    "error",
]


class PendingAction(BaseModel):
    id: str
    type: str
    continuation_tool: str
    candidate_payload: dict[str, Any] = {}


class ToolResult(BaseModel):
    status: ToolStatus
    message: str
    data: dict[str, Any] = {}
    pending_action: PendingAction | None = None
    interaction: InteractionRequest | None = None

    @model_validator(mode="after")
    def validate_interaction_contract(self) -> "ToolResult":
        if self.status in {"needs_user_confirmation", "needs_user_selection"}:
            if self.pending_action is None:
                raise ValueError(f"{self.status} requires pending_action")
            if self.interaction is None:
                raise ValueError(f"{self.status} requires interaction")
        if self.status == "needs_user_input" and self.interaction is None:
            raise ValueError("needs_user_input requires interaction")
        return self
```

- [ ] **Step 5: Implement state**

Create `backend/app/agent/state.py`:

```python
import operator
from typing import Annotated, Any

from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    messages: Annotated[list, operator.add]
    process_events: Annotated[list[dict[str, Any]], operator.add]
    pending_action: dict[str, Any] | None
    interaction: dict[str, Any] | None
    user_decision: dict[str, Any] | None
    response: str | None
    metadata: dict[str, Any]
```

- [ ] **Step 6: Run schema test**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1.AgentV1SchemaTests.test_tool_result_requires_pending_action_for_selection
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/app/agent/hitl backend/app/agent/tools backend/app/agent/state.py backend/test/test_agent_v1.py
git commit -m "feat: define agent hitl schemas"
```

---

## Task 3: Implement Patient Tool And Continuation Handler

**Files:**
- Create: `backend/app/agent/tools/patient.py`
- Create: `backend/app/agent/tools/registry.py`
- Test: `backend/test/test_agent_v1.py`

- [ ] **Step 1: Add failing patient tool tests**

Append to `backend/test/test_agent_v1.py`:

```python
from app.agent.tools.patient import commit_patient_selection, resolve_patient_tool


class PatientToolTests(unittest.TestCase):
    def test_resolve_patient_returns_success_for_mother(self) -> None:
        result = resolve_patient_tool.invoke({"user_text": "帮妈妈存一下报告"})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["patient"]["patient_code"], "mother")

    def test_resolve_patient_returns_selection_for_family(self) -> None:
        result = resolve_patient_tool.invoke({"user_text": "帮家人存一下这个报告"})

        self.assertEqual(result["status"], "needs_user_selection")
        self.assertEqual(result["pending_action"]["continuation_tool"], "commit_patient_selection")
        self.assertEqual(result["interaction"]["type"], "select_one")
        self.assertEqual(result["interaction"]["options"][0]["value"], "mother")

    def test_commit_patient_selection_returns_success_observation(self) -> None:
        result = commit_patient_selection(
            pending_action={
                "id": "pa_001",
                "type": "confirm_patient",
                "continuation_tool": "commit_patient_selection",
                "candidate_payload": {"original_text": "帮家人存一下这个报告"},
            },
            user_decision={"value": "mother", "label": "妈妈"},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["patient"]["patient_code"], "mother")
        self.assertIn("妈妈", result["message"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1.PatientToolTests
```

Expected: FAIL or ERROR because `patient.py` does not exist.

- [ ] **Step 3: Implement patient tool**

Create `backend/app/agent/tools/patient.py`:

```python
from langchain_core.tools import tool

from app.agent.hitl.schemas import InteractionRequest, SelectOption
from app.agent.tools.schemas import PendingAction, ToolResult


PATIENT_OPTIONS = [
    SelectOption(label="妈妈", value="mother"),
    SelectOption(label="爸爸", value="father"),
    SelectOption(label="我自己", value="self"),
    SelectOption(label="新建人物", value="create_patient"),
]


def _dump_result(result: ToolResult) -> dict:
    return result.model_dump(mode="json", exclude_none=True)


@tool
def resolve_patient_tool(user_text: str) -> dict:
    """判断本轮聊天要管理哪个家庭成员的健康档案。"""
    text = user_text.strip()
    direct_matches = [
        ("妈妈", "mother", "妈妈"),
        ("母亲", "mother", "妈妈"),
        ("爸爸", "father", "爸爸"),
        ("父亲", "father", "爸爸"),
        ("我自己", "self", "我自己"),
        ("我的", "self", "我自己"),
    ]
    for keyword, patient_code, display_name in direct_matches:
        if keyword in text:
            return _dump_result(
                ToolResult(
                    status="success",
                    message=f"已识别这次管理对象是{display_name}。",
                    data={
                        "patient": {
                            "patient_code": patient_code,
                            "display_name": display_name,
                        }
                    },
                )
            )

    return _dump_result(
        ToolResult(
            status="needs_user_selection",
            message="我需要先确认这次要管理谁的健康档案。",
            pending_action=PendingAction(
                id="pa_confirm_patient",
                type="confirm_patient",
                continuation_tool="commit_patient_selection",
                candidate_payload={"original_text": text},
            ),
            interaction=InteractionRequest(
                type="select_one",
                title="这次要管理谁的健康档案？",
                description="我需要先确认对象，再继续处理报告或健康信息。",
                options=PATIENT_OPTIONS,
            ),
        )
    )


def commit_patient_selection(
    pending_action: dict,
    user_decision: dict,
) -> dict:
    value = user_decision.get("value")
    label = user_decision.get("label") or {
        "mother": "妈妈",
        "father": "爸爸",
        "self": "我自己",
        "create_patient": "新建人物",
    }.get(value, "未知对象")

    return _dump_result(
        ToolResult(
            status="success",
            message=f"已确认这次管理对象是{label}。",
            data={
                "patient": {
                    "patient_code": value,
                    "display_name": label,
                },
                "source": pending_action.get("candidate_payload", {}),
            },
        )
    )
```

- [ ] **Step 4: Implement registry**

Create `backend/app/agent/tools/registry.py`:

```python
from collections.abc import Callable

from app.agent.tools.patient import commit_patient_selection, resolve_patient_tool


TOOLS = [resolve_patient_tool]

CONTINUATION_HANDLERS: dict[str, Callable[[dict, dict], dict]] = {
    "commit_patient_selection": commit_patient_selection,
}
```

- [ ] **Step 5: Run patient tests**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1.PatientToolTests
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/app/agent/tools/patient.py backend/app/agent/tools/registry.py backend/test/test_agent_v1.py
git commit -m "feat: add patient selection tool"
```

---

## Task 4: Implement HITL Router And LangGraph

**Files:**
- Create: `backend/app/agent/hitl/router.py`
- Create: `backend/app/agent/prompts.py`
- Create: `backend/app/agent/graph.py`
- Test: `backend/test/test_agent_v1.py`

- [ ] **Step 1: Add failing graph interrupt test**

Append to `backend/test/test_agent_v1.py`:

```python
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.graph import graph


class AgentGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_interrupts_and_resumes_patient_selection(self) -> None:
        tool_call_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "resolve_patient_tool",
                    "args": {"user_text": "帮家人存一下这个报告"},
                    "id": "call_resolve_patient",
                }
            ],
        )
        final_response = AIMessage(content="已确认这次管理对象是妈妈。")

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return tool_call_response if self.calls == 1 else final_response

        class FakeLLM:
            def bind_tools(self, tools):
                return FakeBoundLLM()

        config = {"configurable": {"thread_id": "test-patient-selection"}}
        state = {"messages": [{"role": "user", "content": "帮家人存一下这个报告"}]}

        with patch("app.agent.graph.get_openai_llm_stream", return_value=FakeLLM()):
            first = await graph.ainvoke(state, config)
            self.assertIn("__interrupt__", first)
            payload = first["__interrupt__"][0].value
            self.assertEqual(payload["type"], "select_one")
            self.assertEqual(payload["pending_action"]["continuation_tool"], "commit_patient_selection")

            resumed = await graph.ainvoke(Command(resume={"value": "mother", "label": "妈妈"}), config)

        self.assertEqual(resumed["response"], "已确认这次管理对象是妈妈。")
        self.assertEqual(resumed["pending_action"], None)
        self.assertEqual(resumed["interaction"], None)
```

- [ ] **Step 2: Run graph test to verify it fails**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1.AgentGraphTests.test_graph_interrupts_and_resumes_patient_selection
```

Expected: FAIL or ERROR because new graph is not implemented.

- [ ] **Step 3: Implement HITL router**

Create `backend/app/agent/hitl/router.py`:

```python
from typing import Any


def tool_result_needs_interrupt(tool_result: dict[str, Any] | None) -> bool:
    if not tool_result:
        return False
    return tool_result.get("status") in {
        "needs_user_confirmation",
        "needs_user_selection",
        "needs_user_input",
    }


def route_after_tool_result(state: dict[str, Any]) -> str:
    return "human_interrupt" if state.get("interaction") else "call_model"


def route_after_human_interrupt(state: dict[str, Any]) -> str:
    pending_action = state.get("pending_action") or {}
    return "continue_pending_action" if pending_action.get("id") else "call_model"
```

- [ ] **Step 4: Implement prompt**

Create `backend/app/agent/prompts.py`:

```python
SYSTEM_PROMPT = """你是 Memomed，一个家庭医疗助手 Agent。

你需要帮助用户管理家庭成员的健康信息。

当用户表达里出现“家人、妈妈、爸爸、我、报告、存一下、管理健康档案”等内容时，
你应该优先调用 resolve_patient_tool 判断本轮要管理谁的健康档案。

当工具结果表明需要用户确认或选择时，不要自己编造答案，等待系统暂停并向用户展示交互卡片。

医疗安全要求：
- 你不是医生，不能替代专业诊断。
- 涉及诊断、治疗、用药调整时，提醒用户咨询医生。
"""
```

- [ ] **Step 5: Implement graph**

Create `backend/app/agent/graph.py`:

```python
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.agent.hitl.router import route_after_human_interrupt, route_after_tool_result, tool_result_needs_interrupt
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.tools.registry import CONTINUATION_HANDLERS, TOOLS
from app.agent.utils.llm import get_openai_llm_stream


async def call_model(state: AgentState) -> dict[str, Any]:
    llm = get_openai_llm_stream()
    response = await llm.bind_tools(TOOLS).ainvoke(
        [{"role": "system", "content": SYSTEM_PROMPT}] + list(state.get("messages", []))
    )
    return {"messages": [response], "response": getattr(response, "content", "")}


def tools_condition(state: AgentState) -> str:
    last_message = state["messages"][-1]
    return "tools" if getattr(last_message, "tool_calls", None) else "final_answer"


def inspect_tool_result(state: AgentState) -> dict[str, Any]:
    tool_result = _latest_tool_result(state.get("messages", []))
    if tool_result_needs_interrupt(tool_result):
        interaction = dict(tool_result.get("interaction") or {})
        pending_action = tool_result.get("pending_action")
        if pending_action:
            interaction["pending_action"] = pending_action
        return {
            "pending_action": pending_action,
            "interaction": interaction,
            "process_events": [{"type": "thinking", "text": tool_result.get("message", "需要用户确认。")}],
        }
    return {"pending_action": None, "interaction": None}


def human_interrupt(state: AgentState) -> dict[str, Any]:
    user_decision = interrupt(state.get("interaction") or {})
    return {"user_decision": user_decision}


def continue_pending_action(state: AgentState) -> dict[str, Any]:
    pending_action = state.get("pending_action") or {}
    continuation_tool = pending_action.get("continuation_tool")
    handler = CONTINUATION_HANDLERS.get(continuation_tool)
    if handler is None:
        result = {"status": "error", "message": f"未注册续接动作：{continuation_tool}", "data": {}}
    else:
        result = handler(pending_action, state.get("user_decision") or {})

    return {
        "messages": [AIMessage(content=result["message"])],
        "process_events": [{"type": "tool_result", "text": result["message"]}],
        "pending_action": None,
        "interaction": None,
        "response": result["message"],
    }


def final_answer(state: AgentState) -> dict[str, Any]:
    last_message = state["messages"][-1]
    content = last_message.content if isinstance(last_message, AIMessage) else state.get("response") or "处理完成。"
    return {"response": content, "metadata": {"status": "completed"}}


def _latest_tool_result(messages: list) -> dict[str, Any] | None:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            content = message.content
            return content if isinstance(content, dict) else None
    return None


tool_node = ToolNode(TOOLS)

graph = (
    StateGraph(AgentState)
    .add_node("call_model", call_model)
    .add_node("tools", tool_node)
    .add_node("inspect_tool_result", inspect_tool_result)
    .add_node("human_interrupt", human_interrupt)
    .add_node("continue_pending_action", continue_pending_action)
    .add_node("final_answer", final_answer)
    .add_edge(START, "call_model")
    .add_conditional_edges("call_model", tools_condition, {"tools": "tools", "final_answer": "final_answer"})
    .add_edge("tools", "inspect_tool_result")
    .add_conditional_edges(
        "inspect_tool_result",
        route_after_tool_result,
        {"human_interrupt": "human_interrupt", "call_model": "call_model"},
    )
    .add_conditional_edges(
        "human_interrupt",
        route_after_human_interrupt,
        {"continue_pending_action": "continue_pending_action", "call_model": "call_model"},
    )
    .add_edge("continue_pending_action", "call_model")
    .add_edge("final_answer", END)
    .compile(name="memomed_agent", checkpointer=InMemorySaver())
)
```

- [ ] **Step 6: Run graph test**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1.AgentGraphTests.test_graph_interrupts_and_resumes_patient_selection
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/app/agent backend/test/test_agent_v1.py
git commit -m "feat: add minimal agent graph"
```

---

## Task 5: Implement Runtime And FastAPI Routes

**Files:**
- Create: `backend/app/agent/api/schemas.py`
- Create: `backend/app/agent/runtime.py`
- Create: `backend/app/agent/api/routes.py`
- Modify: `backend/app/main.py`
- Test: `backend/test/test_agent_v1.py`

- [ ] **Step 1: Add failing runtime test**

Append to `backend/test/test_agent_v1.py`:

```python
from app.agent.api.schemas import ChatRequest, ResumeRequest
from app.agent.runtime import start_chat


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_chat_returns_thread_id_and_result_shape(self) -> None:
        request = ChatRequest(thread_id="runtime-test-thread", message="帮家人存一下这个报告")

        with patch("app.agent.graph.get_openai_llm_stream") as llm_mock:
            tool_call_response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "resolve_patient_tool",
                        "args": {"user_text": "帮家人存一下这个报告"},
                        "id": "call_resolve_patient",
                    }
                ],
            )

            class FakeBoundLLM:
                async def ainvoke(self, messages):
                    return tool_call_response

            class FakeLLM:
                def bind_tools(self, tools):
                    return FakeBoundLLM()

            llm_mock.return_value = FakeLLM()
            result = await start_chat(request)

        self.assertEqual(result.thread_id, "runtime-test-thread")
        self.assertEqual(result.status, "interrupted")
        self.assertEqual(result.interrupt.type, "select_one")
```

- [ ] **Step 2: Run runtime test to verify it fails**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1.AgentRuntimeTests.test_start_chat_returns_thread_id_and_result_shape
```

Expected: FAIL or ERROR because runtime/API schemas are not implemented.

- [ ] **Step 3: Implement API schemas**

Create `backend/app/agent/api/__init__.py` as an empty file.

Create `backend/app/agent/api/schemas.py`:

```python
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent.hitl.schemas import InteractionRequest


class ChatRequest(BaseModel):
    thread_id: str = Field(default_factory=lambda: f"thread-{uuid4().hex}")
    message: str


class ResumeRequest(BaseModel):
    thread_id: str
    decision: dict[str, Any]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AgentRunResult(BaseModel):
    thread_id: str
    status: Literal["completed", "interrupted", "error"]
    messages: list[ChatMessage] = []
    process_events: list[dict[str, Any]] = []
    interrupt: InteractionRequest | None = None
    error: str | None = None
```

- [ ] **Step 4: Implement runtime**

Create `backend/app/agent/runtime.py`:

```python
from typing import Any

from langgraph.types import Command

from app.agent.api.schemas import AgentRunResult, ChatMessage, ChatRequest, ResumeRequest
from app.agent.graph import graph


async def start_chat(request: ChatRequest) -> AgentRunResult:
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": request.message}], "metadata": {}},
        _config(request.thread_id),
    )
    return _to_run_result(request.thread_id, result)


async def resume_chat(request: ResumeRequest) -> AgentRunResult:
    result = await graph.ainvoke(Command(resume=request.decision), _config(request.thread_id))
    return _to_run_result(request.thread_id, result)


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _to_run_result(thread_id: str, result: dict[str, Any]) -> AgentRunResult:
    interrupts = result.get("__interrupt__")
    if interrupts:
        return AgentRunResult(
            thread_id=thread_id,
            status="interrupted",
            process_events=result.get("process_events", []),
            interrupt=interrupts[0].value,
        )

    response = result.get("response")
    messages = [ChatMessage(role="assistant", content=response)] if response else []
    return AgentRunResult(
        thread_id=thread_id,
        status="completed",
        messages=messages,
        process_events=result.get("process_events", []),
        interrupt=None,
    )
```

- [ ] **Step 5: Implement API routes**

Create `backend/app/agent/api/routes.py`:

```python
from fastapi import APIRouter, HTTPException

from app.agent.api.schemas import AgentRunResult, ChatRequest, ResumeRequest
from app.agent.runtime import resume_chat, start_chat


router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentRunResult)
async def chat(request: ChatRequest) -> AgentRunResult:
    try:
        return await start_chat(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/resume", response_model=AgentRunResult)
async def resume(request: ResumeRequest) -> AgentRunResult:
    try:
        return await resume_chat(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
```

- [ ] **Step 6: Register router in FastAPI app**

Modify `backend/app/main.py` by adding this import near the other imports:

```python
from app.agent.api.routes import router as agent_router
```

Then add after CORS middleware setup:

```python
app.include_router(agent_router)
```

Keep existing `/chat` and `/chat/stream` routes for now as temporary compatibility endpoints. The new Vite frontend will use `/api/agent/chat` and `/api/agent/resume`.

- [ ] **Step 7: Run runtime test**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1.AgentRuntimeTests.test_start_chat_returns_thread_id_and_result_shape
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add backend/app/agent backend/app/main.py backend/test/test_agent_v1.py
git commit -m "feat: expose agent chat api"
```

---

## Task 6: Backup Next Frontend And Scaffold Vite App

**Files:**
- Move: `frontend/` -> `frontend_legacy_backup/`
- Create: `frontend/package.json`
- Create: `frontend/eslint.config.js`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/src/vite-env.d.ts`

- [ ] **Step 1: Move old frontend to backup**

Run:

```bash
mv frontend frontend_legacy_backup
mkdir -p frontend/src
```

Expected: `frontend_legacy_backup/package.json` exists and `frontend/src` exists.

- [ ] **Step 2: Create Vite package**

Create `frontend/package.json`:

```json
{
  "name": "memomed-agent-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview"
  },
  "dependencies": {
    "@tailwindcss/vite": "^4.1.17",
    "@vitejs/plugin-react": "^5.1.2",
    "lucide-react": "^0.577.0",
    "react": "^19.2.3",
    "react-dom": "^19.2.3",
    "tailwindcss": "^4.1.17",
    "vite": "^7.2.7"
  },
  "devDependencies": {
    "@eslint/js": "^9.39.2",
    "@types/node": "^20.19.25",
    "@types/react": "^19.2.7",
    "@types/react-dom": "^19.2.3",
    "eslint": "^9.39.2",
    "eslint-plugin-react-hooks": "^7.0.1",
    "eslint-plugin-react-refresh": "^0.4.24",
    "globals": "^16.5.0",
    "typescript": "^5.9.3",
    "typescript-eslint": "^8.50.0"
  }
}
```

- [ ] **Step 3: Create Vite config**

Create `frontend/vite.config.ts`:

```typescript
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
  },
})
```

- [ ] **Step 4: Create ESLint config**

Create `frontend/eslint.config.js`:

```javascript
import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
)
```

- [ ] **Step 5: Create TypeScript config**

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src"],
  "references": []
}
```

- [ ] **Step 6: Create HTML entry**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Memomed Agent Lab</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 7: Create React entry**

Create `frontend/src/main.tsx`:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

Create `frontend/src/App.tsx`:

```tsx
export default function App() {
  return (
    <main className="min-h-screen bg-stone-50 p-8 text-stone-950">
      <h1 className="text-3xl font-black">Memomed Agent Lab</h1>
      <p className="mt-2 text-stone-600">Vite 前端已启动，下一步接入 Agent Runtime。</p>
    </main>
  )
}
```

Create `frontend/src/index.css`:

```css
@import "tailwindcss";

:root {
  color: #1c1917;
  background: #faf7ef;
  font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}

body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
}

button,
input {
  font: inherit;
}
```

Create `frontend/src/vite-env.d.ts`:

```typescript
/// <reference types="vite/client" />
```

- [ ] **Step 8: Install frontend dependencies**

Run:

```bash
cd frontend
pnpm install
```

Expected: `frontend/pnpm-lock.yaml` is created and dependencies install successfully.

- [ ] **Step 9: Run Vite build**

Run:

```bash
cd frontend
pnpm run build
```

Expected: PASS and `dist/` is generated.

- [ ] **Step 10: Commit**

Run:

```bash
git add frontend frontend_legacy_backup
git commit -m "refactor: replace next frontend with vite shell"
```

---

## Task 7: Implement Frontend Types And API Client

**Files:**
- Create: `frontend/src/types/agent.ts`
- Create: `frontend/src/api/memomedAgentClient.ts`

- [ ] **Step 1: Create frontend types**

Create `frontend/src/types/agent.ts`:

```typescript
export type AgentStatus = 'completed' | 'interrupted' | 'error'

export type SelectOption = {
  label: string
  value: string
}

export type PendingAction = {
  id: string
  type: string
  continuation_tool: string
  candidate_payload?: Record<string, unknown>
}

export type InteractionRequest = {
  type: 'select_one' | 'confirm' | 'text_input'
  title: string
  description?: string | null
  options?: SelectOption[]
  placeholder?: string | null
  pending_action?: PendingAction | null
}

export type AgentMessage = {
  role: 'user' | 'assistant'
  content: string
}

export type ProcessEvent = {
  type: string
  text: string
}

export type AgentRunResult = {
  thread_id: string
  status: AgentStatus
  messages: AgentMessage[]
  process_events: ProcessEvent[]
  interrupt: InteractionRequest | null
  error?: string | null
}
```

- [ ] **Step 2: Create API client**

Create `frontend/src/api/memomedAgentClient.ts`:

```typescript
import type { AgentRunResult } from '@/types/agent'

const BACKEND_BASE_URL = import.meta.env.VITE_BACKEND_BASE_URL ?? 'http://localhost:8010'

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BACKEND_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

export function startAgentChat(input: { thread_id?: string; message: string }) {
  return postJson<AgentRunResult>('/api/agent/chat', input)
}

export function resumeAgentChat(input: { thread_id: string; decision: Record<string, unknown> }) {
  return postJson<AgentRunResult>('/api/agent/resume', input)
}
```

- [ ] **Step 3: Run TypeScript check**

Run:

```bash
cd frontend
pnpm run lint
```

Expected: no new errors from these files.

- [ ] **Step 4: Commit**

Run:

```bash
git add frontend/src/types/agent.ts frontend/src/api/memomedAgentClient.ts
git commit -m "feat: add agent frontend client"
```

---

## Task 8: Implement Frontend Agent Components

**Files:**
- Create: `frontend/src/components/agent/ChatTimeline.tsx`
- Create: `frontend/src/components/agent/ProcessEventCard.tsx`
- Create: `frontend/src/components/agent/InterruptCard.tsx`
- Create: `frontend/src/components/agent/SelectOneCard.tsx`
- Create: `frontend/src/components/agent/ConfirmCard.tsx`
- Create: `frontend/src/components/agent/TextInputCard.tsx`
- Create: `frontend/src/components/agent/Composer.tsx`

- [ ] **Step 1: Create ProcessEventCard**

Create `frontend/src/components/agent/ProcessEventCard.tsx`:

```tsx
import { Sparkles } from 'lucide-react'
import type { ProcessEvent } from '@/types/agent'

export function ProcessEventCard({ event }: { event: ProcessEvent }) {
  return (
    <div className="rounded-2xl border border-teal-200/70 bg-teal-50 px-4 py-3 text-sm text-teal-950 shadow-sm">
      <div className="flex items-center gap-2 font-medium">
        <Sparkles size={16} />
        <span>Agent 过程</span>
      </div>
      <p className="mt-1 text-teal-900/80">{event.text}</p>
    </div>
  )
}
```

- [ ] **Step 2: Create SelectOneCard**

Create `frontend/src/components/agent/SelectOneCard.tsx`:

```tsx
import type { InteractionRequest, SelectOption } from '@/types/agent'

export function SelectOneCard({
  interaction,
  disabled,
  onSelect,
}: {
  interaction: InteractionRequest
  disabled?: boolean
  onSelect: (option: SelectOption) => void
}) {
  return (
    <section className="rounded-3xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">需要你确认</p>
      <h2 className="mt-2 text-lg font-semibold text-stone-950">{interaction.title}</h2>
      {interaction.description ? <p className="mt-1 text-sm text-stone-600">{interaction.description}</p> : null}
      <div className="mt-4 grid grid-cols-2 gap-3">
        {(interaction.options ?? []).map((option) => (
          <button
            key={option.value}
            disabled={disabled}
            onClick={() => onSelect(option)}
            className="rounded-2xl border border-amber-200 bg-white px-4 py-3 text-left font-medium text-stone-900 transition hover:-translate-y-0.5 hover:border-amber-400 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60"
          >
            {option.label}
          </button>
        ))}
      </div>
    </section>
  )
}
```

- [ ] **Step 3: Create ConfirmCard**

Create `frontend/src/components/agent/ConfirmCard.tsx`:

```tsx
import type { InteractionRequest } from '@/types/agent'

export function ConfirmCard({
  interaction,
  disabled,
  onConfirm,
}: {
  interaction: InteractionRequest
  disabled?: boolean
  onConfirm: (confirmed: boolean) => void
}) {
  return (
    <section className="rounded-3xl border border-sky-200 bg-sky-50 p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-stone-950">{interaction.title}</h2>
      {interaction.description ? <p className="mt-1 text-sm text-stone-600">{interaction.description}</p> : null}
      <div className="mt-4 flex gap-3">
        <button disabled={disabled} onClick={() => onConfirm(true)} className="rounded-xl bg-sky-700 px-4 py-2 text-white disabled:opacity-60">
          确认
        </button>
        <button disabled={disabled} onClick={() => onConfirm(false)} className="rounded-xl border border-sky-200 bg-white px-4 py-2 text-sky-900 disabled:opacity-60">
          取消
        </button>
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Create TextInputCard**

Create `frontend/src/components/agent/TextInputCard.tsx`:

```tsx
'use client'

import { useState } from 'react'
import type { InteractionRequest } from '@/types/agent'

export function TextInputCard({
  interaction,
  disabled,
  onSubmit,
}: {
  interaction: InteractionRequest
  disabled?: boolean
  onSubmit: (value: string) => void
}) {
  const [value, setValue] = useState('')

  return (
    <section className="rounded-3xl border border-lime-200 bg-lime-50 p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-stone-950">{interaction.title}</h2>
      {interaction.description ? <p className="mt-1 text-sm text-stone-600">{interaction.description}</p> : null}
      <div className="mt-4 flex gap-2">
        <input
          value={value}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          placeholder={interaction.placeholder ?? '请输入补充信息'}
          className="min-w-0 flex-1 rounded-xl border border-lime-200 bg-white px-4 py-2 outline-none focus:border-lime-500"
        />
        <button disabled={disabled || !value.trim()} onClick={() => onSubmit(value)} className="rounded-xl bg-lime-700 px-4 py-2 text-white disabled:opacity-60">
          提交
        </button>
      </div>
    </section>
  )
}
```

- [ ] **Step 5: Create InterruptCard**

Create `frontend/src/components/agent/InterruptCard.tsx`:

```tsx
import type { InteractionRequest, SelectOption } from '@/types/agent'
import { ConfirmCard } from './ConfirmCard'
import { SelectOneCard } from './SelectOneCard'
import { TextInputCard } from './TextInputCard'

export function InterruptCard({
  interaction,
  disabled,
  onDecision,
}: {
  interaction: InteractionRequest
  disabled?: boolean
  onDecision: (decision: Record<string, unknown>) => void
}) {
  if (interaction.type === 'select_one') {
    return (
      <SelectOneCard
        interaction={interaction}
        disabled={disabled}
        onSelect={(option: SelectOption) => onDecision({ value: option.value, label: option.label })}
      />
    )
  }

  if (interaction.type === 'confirm') {
    return <ConfirmCard interaction={interaction} disabled={disabled} onConfirm={(confirmed) => onDecision({ confirmed })} />
  }

  return <TextInputCard interaction={interaction} disabled={disabled} onSubmit={(value) => onDecision({ value })} />
}
```

- [ ] **Step 6: Create ChatTimeline**

Create `frontend/src/components/agent/ChatTimeline.tsx`:

```tsx
import { Bot, User } from 'lucide-react'
import type { AgentMessage, ProcessEvent } from '@/types/agent'
import { ProcessEventCard } from './ProcessEventCard'

export function ChatTimeline({
  messages,
  processEvents,
}: {
  messages: AgentMessage[]
  processEvents: ProcessEvent[]
}) {
  return (
    <div className="space-y-5">
      {messages.map((message, index) => (
        <div key={`${message.role}-${index}`} className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          {message.role === 'assistant' ? <Bot className="mt-2 text-teal-700" size={20} /> : null}
          <div className={`max-w-[78%] rounded-3xl px-5 py-3 shadow-sm ${message.role === 'user' ? 'bg-stone-950 text-white' : 'border border-stone-200 bg-white text-stone-950'}`}>
            {message.content}
          </div>
          {message.role === 'user' ? <User className="mt-2 text-stone-700" size={20} /> : null}
        </div>
      ))}
      {processEvents.map((event, index) => (
        <ProcessEventCard key={`${event.type}-${index}`} event={event} />
      ))}
    </div>
  )
}
```

- [ ] **Step 7: Create Composer**

Create `frontend/src/components/agent/Composer.tsx`:

```tsx
'use client'

import { Send } from 'lucide-react'
import { useState } from 'react'

export function Composer({
  disabled,
  onSend,
}: {
  disabled?: boolean
  onSend: (message: string) => void
}) {
  const [value, setValue] = useState('')

  function submit() {
    const message = value.trim()
    if (!message) return
    onSend(message)
    setValue('')
  }

  return (
    <div className="rounded-3xl border border-stone-200 bg-white p-2 shadow-xl shadow-stone-200/70">
      <div className="flex items-center gap-2">
        <input
          value={value}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit()
          }}
          placeholder="试试：帮家人存一下这个报告"
          className="min-w-0 flex-1 rounded-2xl px-4 py-3 text-stone-950 outline-none"
        />
        <button
          disabled={disabled || !value.trim()}
          onClick={submit}
          className="rounded-2xl bg-teal-700 p-3 text-white transition hover:bg-teal-600 disabled:bg-stone-300"
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 8: Run frontend lint**

Run:

```bash
cd frontend
pnpm run lint
```

Expected: no new component lint errors.

- [ ] **Step 9: Commit**

Run:

```bash
git add frontend/src/components/agent
git commit -m "feat: add agent interrupt components"
```

---

## Task 9: Replace Vite App With Custom Agent Test Page

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Replace page implementation**

Replace `frontend/src/App.tsx` with:

```tsx
import { useState } from 'react'
import { startAgentChat, resumeAgentChat } from '@/api/memomedAgentClient'
import { ChatTimeline } from '@/components/agent/ChatTimeline'
import { Composer } from '@/components/agent/Composer'
import { InterruptCard } from '@/components/agent/InterruptCard'
import type { AgentMessage, AgentRunResult, InteractionRequest, ProcessEvent } from '@/types/agent'

export default function Home() {
  const [threadId, setThreadId] = useState<string | null>(null)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [processEvents, setProcessEvents] = useState<ProcessEvent[]>([])
  const [interrupt, setInterrupt] = useState<InteractionRequest | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSend(message: string) {
    setIsLoading(true)
    setError(null)
    setMessages((current) => [...current, { role: 'user', content: message }])

    try {
      const result = await startAgentChat({ thread_id: threadId ?? undefined, message })
      applyResult(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : '发送失败')
    } finally {
      setIsLoading(false)
    }
  }

  async function handleDecision(decision: Record<string, unknown>) {
    if (!threadId) return
    setIsLoading(true)
    setError(null)

    try {
      const result = await resumeAgentChat({ thread_id: threadId, decision })
      applyResult(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交选择失败')
    } finally {
      setIsLoading(false)
    }
  }

  function applyResult(result: AgentRunResult) {
    setThreadId(result.thread_id)
    setProcessEvents((current) => [...current, ...result.process_events])
    setInterrupt(result.interrupt)
    if (result.messages.length > 0) {
      setMessages((current) => [...current, ...result.messages])
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,#d9f99d_0,#f7f3ea_34%,#fdfaf3_100%)] text-stone-950">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-5 py-6">
        <header className="mb-6 flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-800">Memomed Agent Lab</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight md:text-5xl">家庭医疗助手测试台</h1>
            <p className="mt-2 max-w-2xl text-sm text-stone-600">
              第一版专注测试 Agent Loop、过程展示和 interrupt 选择题。健康建议仅供参考，请以医生意见为准。
            </p>
          </div>
          <div className="rounded-2xl border border-stone-200 bg-white/70 px-4 py-3 text-xs text-stone-600 shadow-sm">
            Thread: {threadId ?? '未开始'}
          </div>
        </header>

        <section className="flex-1 rounded-[2rem] border border-white/70 bg-white/55 p-4 shadow-2xl shadow-stone-300/40 backdrop-blur">
          <ChatTimeline messages={messages} processEvents={processEvents} />
          {interrupt ? (
            <div className="mt-5">
              <InterruptCard interaction={interrupt} disabled={isLoading} onDecision={handleDecision} />
            </div>
          ) : null}
          {error ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
        </section>

        <footer className="mt-5">
          <Composer disabled={isLoading || Boolean(interrupt)} onSend={handleSend} />
          {interrupt ? <p className="mt-2 text-center text-xs text-stone-500">请先完成上方确认，再继续输入新消息。</p> : null}
        </footer>
      </div>
    </main>
  )
}
```

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd frontend
pnpm run build
```

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```bash
git add frontend/src/App.tsx
git commit -m "feat: add memomed agent test page"
```

---

## Task 10: End-To-End Verification And Cleanup

**Files:**
- Modify if needed: files touched by previous tasks only.

- [ ] **Step 1: Run backend unit tests for new Agent**

Run:

```bash
cd backend
uv run python -m unittest test.test_agent_v1
```

Expected: all tests in `test_agent_v1` PASS.

- [ ] **Step 2: Run backend import checks**

Run:

```bash
cd backend
uv run python -m py_compile app/agent/graph.py app/agent/runtime.py app/agent/api/routes.py app/main.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run frontend lint**

Run:

```bash
cd frontend
pnpm run lint
```

Expected: PASS.

- [ ] **Step 4: Manual local smoke test**

Run backend:

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8010
```

Run frontend in another terminal:

```bash
cd frontend
pnpm run dev
```

Open the frontend and test:

```text
1. 输入：帮家人存一下这个报告
2. 页面显示 Agent 过程卡片
3. 页面显示“这次要管理谁的健康档案？”
4. 点击“妈妈”
5. 页面显示“已确认这次管理对象是妈妈。”
```

- [ ] **Step 5: Check no runtime import uses legacy agent**

Run:

```bash
rg -n "agent_legacy_backup" backend/app frontend/src
```

Expected: no matches outside `backend/app/agent_legacy_backup/README.md`.

- [ ] **Step 6: Final commit if smoke fixes were needed**

If any smoke-test fixes were made, run:

```bash
git add backend/app frontend/src backend/test/test_agent_v1.py
git commit -m "fix: stabilize agent v1 smoke flow"
```

If no fixes were made, do not create an empty commit.

---

## Self-Review

### Spec Coverage

- 旧 Agent 备份：Task 1。
- 新 `app/agent/` 原地重写：Tasks 2-5。
- Tool result contract：Task 2。
- Patient selection tool：Task 3。
- LangGraph interrupt/resume：Task 4。
- FastAPI chat/resume API：Task 5。
- 旧 Next 前端备份 + Vite 重建：Task 6。
- 前端 API client 和 interrupt 组件：Tasks 7-8。
- 自定义前端页面：Task 9。
- E2E 验收：Task 10。

### Scope Control

第一版没有实现 OCR、RAG、报告入库、用药提醒、多 Agent 或完整家庭成员管理。所有这些能力保留到后续扩展。

### Type Consistency

后端使用 `InteractionRequest.type = select_one | confirm | text_input`。前端 `InteractionRequest` 类型保持同名字段。后端 `continuation_tool` 字段与前端 `PendingAction.continuation_tool` 保持一致。

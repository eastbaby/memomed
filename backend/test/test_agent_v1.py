import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command

from app.agent.api.schemas import ChatRequest
from app.agent.graph import graph
from app.agent.hitl.schemas import InteractionRequest, SelectOption
from app.agent.runtime import _to_run_result, start_chat, stream_start_chat
from app.agent.api.routes import _sse_event, _stream_headers
from app.agent.tools.patient import (
    PatientGrounding,
    SubjectCandidate,
    _selection_options,
    commit_patient_selection,
    resolve_patient_tool,
)
from app.agent.tools.schemas import PendingAction, ToolResult
from app.subjects.service import DuplicateAliasError


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

def _subject(
    subject_id: str,
    patient_code: str,
    display_name: str,
    patient_type: str = "human",
) -> SubjectCandidate:
    return SubjectCandidate(
        subject_id=subject_id,
        patient_code=patient_code,
        display_name=display_name,
        patient_type=patient_type,
        aliases=[display_name, patient_code],
    )


class PatientToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_patient_returns_success_for_mother(self) -> None:
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="resolved",
            matched_subject_id="subject-mother",
            patient_code="mother",
            display_name="妈妈",
            patient_type="human",
            confidence="high",
            reason="用户明确提到妈妈。",
            next_action="continue",
        )
        candidates = [_subject("subject-mother", "mother", "妈妈")]

        with (
            patch("app.agent.tools.patient.list_subject_candidates", return_value=candidates),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            result = await resolve_patient_tool.ainvoke({"user_text": "帮妈妈存一下报告"})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["patient"]["patient_code"], "mother")
        self.assertEqual(result["data"]["patient"]["subject_id"], "subject-mother")

    async def test_resolve_patient_treats_my_cat_as_pet_not_self(self) -> None:
        grounding = PatientGrounding(
            intent="pet_health",
            resolution_status="resolved",
            matched_subject_id="subject-cat",
            patient_code="pet_cat",
            display_name="猫咪",
            patient_type="pet",
            species="cat",
            confidence="high",
            reason="“我的”是所有格，主体是猫咪。",
            next_action="continue",
        )
        candidates = [_subject("subject-cat", "pet_cat", "猫咪", patient_type="pet")]

        with (
            patch("app.agent.tools.patient.list_subject_candidates", return_value=candidates),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            result = await resolve_patient_tool.ainvoke({"user_text": "我的猫咪"})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["patient"]["patient_code"], "pet_cat")
        self.assertEqual(result["data"]["patient"]["patient_type"], "pet")
        self.assertEqual(result["data"]["patient"]["subject_id"], "subject-cat")
        self.assertNotEqual(result["data"]["patient"]["patient_code"], "self")

    async def test_resolve_patient_uses_self_candidate_for_first_person_subject(self) -> None:
        candidates = [
            _subject("subject-self", "self", "我"),
            _subject("subject-cat", "pet_cat", "猫咪", patient_type="pet"),
        ]

        with (
            patch("app.agent.tools.patient.list_subject_candidates", return_value=candidates),
            patch("app.agent.tools.patient.classify_patient_grounding") as classifier,
        ):
            result = await resolve_patient_tool.ainvoke({"user_text": "帮我看下我上次吃的什么药"})

        classifier.assert_not_awaited()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["patient"]["subject_id"], "subject-self")

    async def test_resolve_patient_does_not_treat_possessive_relative_as_self(self) -> None:
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="resolved",
            matched_subject_id="subject-mother",
            patient_code="mother",
            display_name="妈妈",
            patient_type="human",
            confidence="high",
            reason="“我的妈妈”里的“我的”是亲属所有格，主体是妈妈。",
            next_action="continue",
        )
        candidates = [
            _subject("subject-self", "self", "我"),
            _subject("subject-mother", "mother", "妈妈"),
        ]

        with (
            patch("app.agent.tools.patient.list_subject_candidates", return_value=candidates),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding) as classifier,
        ):
            result = await resolve_patient_tool.ainvoke({"user_text": "我的妈妈上次体检报告"})

        classifier.assert_awaited_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["patient"]["subject_id"], "subject-mother")
        self.assertNotEqual(result["data"]["patient"]["subject_id"], "subject-self")

    async def test_resolve_patient_returns_selection_for_family(self) -> None:
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="ambiguous",
            confidence="low",
            reason="用户只说家人，没有明确对象。",
            next_action="ask_patient_selection",
        )
        candidates = [
            _subject("subject-mother", "mother", "妈妈"),
            _subject("subject-cat", "pet_cat", "猫咪", patient_type="pet"),
        ]

        with (
            patch("app.agent.tools.patient.list_subject_candidates", return_value=candidates),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            result = await resolve_patient_tool.ainvoke({"user_text": "帮家人存一下这个报告"})

        self.assertEqual(result["status"], "needs_user_selection")
        self.assertEqual(result["pending_action"]["continuation_tool"], "commit_patient_selection")
        self.assertEqual(result["interaction"]["type"], "select_one")
        self.assertEqual(result["interaction"]["options"][0]["value"], "subject:subject-mother")
        option_values = [option["value"] for option in result["interaction"]["options"]]
        self.assertIn("subject:subject-cat", option_values)
        self.assertIn("create_pet", option_values)

    def test_selection_options_are_database_driven_subjects(self) -> None:
        candidates = [
            _subject("subject-mother", "subject-mother", "妈妈"),
            _subject("subject-cat", "subject-cat", "小橘", patient_type="pet"),
        ]

        options = _selection_options(candidates)

        self.assertEqual(options[0].value, "subject:subject-mother")
        self.assertEqual(options[0].label, "妈妈（成员）")
        self.assertEqual(options[1].value, "subject:subject-cat")
        self.assertEqual(options[1].label, "小橘（宠物）")
        self.assertEqual(options[-2].value, "create_patient")
        self.assertEqual(options[-1].value, "create_pet")

    async def test_resolve_patient_returns_not_applicable_for_non_health_subject(self) -> None:
        grounding = PatientGrounding(
            intent="general_chat",
            resolution_status="not_applicable",
            confidence="high",
            reason="用户说的是手机，不是人或宠物健康档案。",
            next_action="ask_clarifying_question",
        )

        with (
            patch("app.agent.tools.patient.list_subject_candidates", return_value=[]),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            result = await resolve_patient_tool.ainvoke({"user_text": "我的手机"})

        self.assertEqual(result["status"], "not_applicable")
        self.assertIn("手机", result["data"]["reason"])

    async def test_commit_patient_selection_returns_success_observation(self) -> None:
        result = await commit_patient_selection(
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

    async def test_commit_patient_selection_asks_name_when_creating_pet(self) -> None:
        result = await commit_patient_selection(
            pending_action={
                "id": "pa_001",
                "type": "confirm_patient",
                "continuation_tool": "commit_patient_selection",
                "candidate_payload": {
                    "original_text": "我的猫咪",
                    "grounding": {"species": "cat"},
                },
            },
            user_decision={"value": "create_pet", "label": "新建宠物"},
        )

        self.assertEqual(result["status"], "needs_user_input")
        self.assertEqual(result["pending_action"]["type"], "create_subject_name")
        self.assertEqual(result["pending_action"]["candidate_payload"]["subject_type"], "pet")
        self.assertEqual(result["interaction"]["type"], "text_input")

    async def test_commit_patient_selection_creates_subject_from_name(self) -> None:
        created_subject = type(
            "CreatedSubject",
            (),
            {
                "id": "subject-new-cat",
                "display_name": "小橘",
                "subject_type": "pet",
                "legal_name": None,
            },
        )()

        with patch("app.agent.tools.patient.create_subject", return_value=created_subject) as create_subject_mock:
            result = await commit_patient_selection(
                pending_action={
                    "id": "pa_create_pet",
                    "type": "create_subject_name",
                    "continuation_tool": "commit_patient_selection",
                    "candidate_payload": {
                        "original_text": "我的猫咪",
                        "subject_type": "pet",
                        "grounding": {"species": "cat"},
                    },
                },
                user_decision={"value": "小橘"},
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["patient"]["subject_id"], "subject-new-cat")
        create_payload = create_subject_mock.call_args.args[0]
        self.assertEqual(create_payload.display_name, "小橘")
        self.assertEqual(create_payload.subject_type, "pet")
        self.assertEqual(create_payload.species, "cat")

    async def test_commit_patient_selection_creates_human_subject_from_name(self) -> None:
        created_subject = type(
            "CreatedSubject",
            (),
            {
                "id": "subject-new-mother",
                "display_name": "妈妈",
                "subject_type": "human",
                "legal_name": None,
            },
        )()

        with patch("app.agent.tools.patient.create_subject", return_value=created_subject) as create_subject_mock:
            result = await commit_patient_selection(
                pending_action={
                    "id": "pa_create_human",
                    "type": "create_subject_name",
                    "continuation_tool": "commit_patient_selection",
                    "candidate_payload": {
                        "original_text": "帮我妈存报告",
                        "subject_type": "human",
                    },
                },
                user_decision={"value": "妈妈"},
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["patient"]["subject_id"], "subject-new-mother")
        create_payload = create_subject_mock.call_args.args[0]
        self.assertEqual(create_payload.display_name, "妈妈")
        self.assertEqual(create_payload.subject_type, "human")
        self.assertIsNone(create_payload.species)

    async def test_commit_patient_selection_returns_structured_error_for_duplicate_alias(self) -> None:
        with patch("app.agent.tools.patient.create_subject", side_effect=DuplicateAliasError("重复别名")):
            result = await commit_patient_selection(
                pending_action={
                    "id": "pa_create_human",
                    "type": "create_subject_name",
                    "continuation_tool": "commit_patient_selection",
                    "candidate_payload": {
                        "original_text": "帮我爷爷存报告",
                        "subject_type": "human",
                    },
                },
                user_decision={"value": "爷爷"},
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("别名“爷爷”已经被其他成员或宠物使用", result["message"])
        self.assertEqual(result["data"], {})


class AgentGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_model_merges_handoff_context_into_single_system_message(self) -> None:
        from app.agent.graph import call_model

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.messages = []

            async def ainvoke(self, messages):
                self.messages = messages
                return AIMessage(content="已完成")

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        fake_llm = FakeLLM()

        with patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm):
            await call_model(
                {
                    "messages": [{"role": "user", "content": "帮我新建妈妈"}],
                    "handoff_context": "已新建人物档案：妈妈，并确认这次管理对象是妈妈。",
                }
            )

        system_messages = [message for message in fake_llm.bound.messages if message.get("role") == "system"]
        self.assertEqual(len(system_messages), 1)
        self.assertIn("已新建人物档案：妈妈", system_messages[0]["content"])

    async def test_call_model_prunes_old_pending_tool_messages_after_handoff(self) -> None:
        from app.agent.graph import call_model

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.messages = []

            async def ainvoke(self, messages):
                self.messages = messages
                return AIMessage(content="已完成")

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        fake_llm = FakeLLM()

        with patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm):
            await call_model(
                {
                    "messages": [
                        {"role": "user", "content": "我上次带我妈做了体检，报告是啥"},
                        AIMessage(content="之前已经帮你整理过一次体检报告摘要。"),
                        {"role": "user", "content": "现在先帮我确认这份新报告的对象"},
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "resolve_patient_tool",
                                    "args": {"user_text": "我上次带我妈做了体检，报告是啥"},
                                    "id": "call_old_selection",
                                }
                            ],
                        ),
                        ToolMessage(
                            content='{"status":"needs_user_selection","message":"需要确认本次健康档案的管理对象。"}',
                            tool_call_id="call_old_selection",
                        ),
                    ],
                    "handoff_context": "已新建人物档案：婆婆，并确认这次管理对象是婆婆。",
                }
            )

        contents = [getattr(message, "content", None) if not isinstance(message, dict) else message.get("content") for message in fake_llm.bound.messages]
        self.assertIn("我上次带我妈做了体检，报告是啥", contents)
        self.assertIn("之前已经帮你整理过一次体检报告摘要。", contents)
        self.assertIn("现在先帮我确认这份新报告的对象", contents)
        self.assertFalse(any("需要确认本次健康档案的管理对象" in str(content) for content in contents))

    async def test_call_model_prunes_dict_shaped_tool_trace_after_handoff(self) -> None:
        from app.agent.graph import call_model

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.messages = []

            async def ainvoke(self, messages):
                self.messages = messages
                return AIMessage(content="已完成")

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        fake_llm = FakeLLM()

        with patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm):
            await call_model(
                {
                    "messages": [
                        {"role": "user", "content": "看下我奶奶的报告"},
                        {"role": "assistant", "content": "可以，我会先确认健康档案对象。"},
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "name": "resolve_patient_tool",
                                    "args": {"user_text": "看下我奶奶的报告"},
                                    "id": "call_dict_trace",
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "call_dict_trace",
                            "content": '{"status":"needs_user_selection","message":"需要确认本次健康档案的管理对象。"}',
                        },
                    ],
                    "handoff_context": "已新建人物档案：奶奶，并确认这次管理对象是奶奶。",
                }
            )

        contents = [message.get("content") if isinstance(message, dict) else getattr(message, "content", "") for message in fake_llm.bound.messages]
        roles = [message.get("role") for message in fake_llm.bound.messages if isinstance(message, dict)]
        self.assertIn("看下我奶奶的报告", contents)
        self.assertIn("可以，我会先确认健康档案对象。", contents)
        self.assertNotIn("tool", roles)
        self.assertFalse(any("需要确认本次健康档案的管理对象" in str(content) for content in contents))

    async def test_call_model_keeps_tool_registry_stable_after_subject_resolution(self) -> None:
        from app.agent.graph import call_model

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.messages = []

            async def ainvoke(self, messages):
                self.messages = messages
                return AIMessage(content="已确认对象是妈妈。")

        class FakeLLM:
            def __init__(self) -> None:
                self.bound_tool_names = []
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                self.bound_tool_names = [tool.name for tool in tools]
                return self.bound

        fake_llm = FakeLLM()

        with patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm):
            await call_model(
                {
                    "messages": [{"role": "user", "content": "看下我妈上次报告"}],
                    "handoff_context": "已确认这次管理对象是妈妈（成员）。",
                    "agent_context": {
                        "subject": {"subject_id": "subject-mother", "display_name": "妈妈", "patient_type": "human"}
                    },
                    "satisfied_capabilities": {
                        "subject_resolution": {
                            "turn_key": "看下我妈上次报告",
                            "message": "已确认这次管理对象是妈妈（成员）。",
                            "data": {
                                "patient": {
                                    "subject_id": "subject-mother",
                                    "display_name": "妈妈",
                                    "patient_type": "human",
                                }
                            },
                        }
                    },
                }
            )

        self.assertIn("resolve_patient_tool", fake_llm.bound_tool_names)
        self.assertIn("query_health_records_tool", fake_llm.bound_tool_names)
        system_messages = [message for message in fake_llm.bound.messages if message.get("role") == "system"]
        self.assertIn("subject-mother", system_messages[0]["content"])
        self.assertIn("不要重复询问已经确认的信息", system_messages[0]["content"])

    async def test_call_model_keeps_patient_resolution_available_for_new_user_turn(self) -> None:
        from app.agent.graph import call_model

        class FakeBoundLLM:
            async def ainvoke(self, messages):
                return AIMessage(content="我会重新确认对象。")

        class FakeLLM:
            def __init__(self) -> None:
                self.bound_tool_names = []
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                self.bound_tool_names = [tool.name for tool in tools]
                return self.bound

        fake_llm = FakeLLM()

        with patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm):
            await call_model(
                {
                    "messages": [
                        {"role": "user", "content": "看下我妈上次报告"},
                        AIMessage(content="已确认对象是妈妈。"),
                        {"role": "user", "content": "换成奶奶，我要看奶奶的"},
                    ],
                    "handoff_context": "已确认这次管理对象是妈妈（成员）。",
                    "agent_context": {
                        "subject": {"subject_id": "subject-mother", "display_name": "妈妈", "patient_type": "human"}
                    },
                    "satisfied_capabilities": {
                        "subject_resolution": {
                            "turn_key": "看下我妈上次报告",
                            "message": "已确认这次管理对象是妈妈（成员）。",
                            "data": {"patient": {"subject_id": "subject-mother", "display_name": "妈妈"}},
                        }
                    },
                }
            )

        self.assertIn("resolve_patient_tool", fake_llm.bound_tool_names)

    async def test_tool_runtime_returns_already_satisfied_for_same_turn_subject_resolution(self) -> None:
        from app.agent.tool_runtime import execute_tool_call
        from app.agent.tools.registry import TOOL_SPECS

        class FailingTool:
            async def ainvoke(self, args):
                raise AssertionError("同一轮已满足时不应该再次执行真实工具")

        result = await execute_tool_call(
            {
                "name": "resolve_patient_tool",
                "args": {"user_text": "看下我妈上次报告"},
                "id": "call_resolve_repeat",
            },
            {
                "messages": [{"role": "user", "content": "看下我妈上次报告"}],
                "satisfied_capabilities": {
                    "subject_resolution": {
                        "turn_key": "看下我妈上次报告",
                        "message": "已确认这次管理对象是妈妈（成员）。",
                        "data": {
                            "patient": {
                                "subject_id": "subject-mother",
                                "display_name": "妈妈",
                                "patient_type": "human",
                            }
                        },
                    }
                },
            },
            tools_by_name={"resolve_patient_tool": FailingTool()},
            tool_specs=TOOL_SPECS,
        )

        self.assertEqual(result["status"], "already_satisfied")
        self.assertEqual(result["data"]["patient"]["subject_id"], "subject-mother")

    async def test_tool_runtime_allows_subject_resolution_for_new_user_turn(self) -> None:
        from app.agent.tool_runtime import execute_tool_call
        from app.agent.tools.registry import TOOL_SPECS

        class RecordingTool:
            def __init__(self) -> None:
                self.called = False

            async def ainvoke(self, args):
                self.called = True
                return {"status": "success", "message": "已识别这次管理对象是奶奶。", "data": {}}

        tool = RecordingTool()

        result = await execute_tool_call(
            {
                "name": "resolve_patient_tool",
                "args": {"user_text": "换成奶奶，我要看奶奶的"},
                "id": "call_resolve_switch",
            },
            {
                "messages": [
                    {"role": "user", "content": "看下我妈上次报告"},
                    AIMessage(content="已确认对象是妈妈。"),
                    {"role": "user", "content": "换成奶奶，我要看奶奶的"},
                ],
                "satisfied_capabilities": {
                    "subject_resolution": {
                        "turn_key": "看下我妈上次报告",
                        "message": "已确认这次管理对象是妈妈（成员）。",
                        "data": {"patient": {"subject_id": "subject-mother", "display_name": "妈妈"}},
                    }
                },
            },
            tools_by_name={"resolve_patient_tool": tool},
            tool_specs=TOOL_SPECS,
        )

        self.assertTrue(tool.called)
        self.assertEqual(result["status"], "success")

    async def test_query_health_records_tool_returns_capability_missing(self) -> None:
        from app.agent.tools.records import query_health_records_tool

        result = await query_health_records_tool.ainvoke(
            {
                "subject_id": "subject-father",
                "record_type": "hospitalization_report",
                "limit": 5,
            }
        )

        self.assertEqual(result["status"], "capability_missing")
        self.assertIn("报告查询工具尚未接入", result["message"])

    async def test_call_model_retries_when_llm_outputs_fake_tool_call_text(self) -> None:
        from app.agent.graph import call_model

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content='好的，我来查询。<tool_call>{"name":"query_health_records","parameters":{}}</tool_call>'
                    )
                return AIMessage(content="已确认对象是爸爸，但当前还没有接入报告查询工具。")

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        fake_llm = FakeLLM()

        with patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm):
            result = await call_model(
                {
                    "messages": [{"role": "user", "content": "帮我看下我爸住院报告"}],
                    "handoff_context": "已确认这次管理对象是爸爸（成员）。",
                    "current_subject": {"subject_id": "subject-father", "display_name": "爸爸", "patient_type": "human"},
                    "subject_resolution_status": "resolved",
                    "subject_resolution_turn_key": "帮我看下我爸住院报告",
                }
            )

        self.assertEqual(fake_llm.bound.calls, 2)
        self.assertNotIn("<tool_call>", result["response"])
        self.assertEqual(result["response"], "已确认对象是爸爸，但当前还没有接入报告查询工具。")

    async def test_call_model_marks_invalid_when_fake_tool_call_retry_still_fails(self) -> None:
        from app.agent.graph import call_model

        class FakeBoundLLM:
            async def ainvoke(self, messages):
                return AIMessage(content='<tool_call>{"name":"query_health_records"}</tool_call>')

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        with patch("app.agent.graph.get_openai_llm_stream", return_value=FakeLLM()):
            result = await call_model(
                {
                    "messages": [{"role": "user", "content": "帮我看下我爸住院报告"}],
                    "handoff_context": "已确认这次管理对象是爸爸（成员）。",
                    "current_subject": {"subject_id": "subject-father", "display_name": "爸爸", "patient_type": "human"},
                    "subject_resolution_status": "resolved",
                    "subject_resolution_turn_key": "帮我看下我爸住院报告",
                }
            )

        self.assertEqual(result["response"], "")
        self.assertEqual(result["metadata"]["status"], "llm_invalid_tool_call_text")

    async def test_graph_finishes_after_successful_patient_resolution(self) -> None:
        tool_call_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "resolve_patient_tool",
                    "args": {"user_text": "我想帮我爸看下他之前的体检报告"},
                    "id": "call_resolve_patient",
                }
            ],
        )

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return tool_call_response
                return AIMessage(content="已确认对象是爸爸。你可以继续上传或发送他的体检报告。")

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        fake_llm = FakeLLM()
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="resolved",
            matched_subject_id="subject-father",
            patient_code="father",
            display_name="爸爸",
            patient_type="human",
            confidence="high",
            reason="用户明确提到爸爸。",
            next_action="continue",
        )
        candidates = [_subject("subject-father", "father", "爸爸")]

        with (
            patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm),
            patch("app.agent.tools.patient.list_subject_candidates", return_value=candidates),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": "我想帮我爸看下他之前的体检报告"}]},
                {"configurable": {"thread_id": "test-successful-resolution-stops"}},
            )

        self.assertEqual(fake_llm.bound.calls, 2)
        self.assertEqual(result["response"], "已确认对象是爸爸。你可以继续上传或发送他的体检报告。")
        self.assertNotIn("__interrupt__", result)

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
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        config = {"configurable": {"thread_id": "test-patient-selection"}}
        state = {"messages": [{"role": "user", "content": "帮家人存一下这个报告"}]}
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="ambiguous",
            confidence="low",
            reason="用户只说家人，没有明确对象。",
            next_action="ask_patient_selection",
        )

        with (
            patch("app.agent.graph.get_openai_llm_stream", return_value=FakeLLM()),
            patch("app.agent.tools.patient.list_subject_candidates", return_value=[]),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            first = await graph.ainvoke(state, config)
            self.assertIn("__interrupt__", first)
            payload = first["__interrupt__"][0].value
            self.assertEqual(payload["type"], "select_one")
            self.assertEqual(payload["pending_action"]["continuation_tool"], "commit_patient_selection")

            resumed = await graph.ainvoke(Command(resume={"value": "mother", "label": "妈妈"}), config)

        self.assertEqual(resumed["response"], "已确认这次管理对象是妈妈。")
        self.assertEqual(resumed["pending_action"], None)
        self.assertEqual(resumed["interaction"], None)

    async def test_graph_does_not_complete_with_empty_llm_answer_after_resume(self) -> None:
        tool_call_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "resolve_patient_tool",
                    "args": {"user_text": "帮家人存一下这个报告"},
                    "id": "call_resolve_patient_empty_final",
                }
            ],
        )
        empty_final_response = AIMessage(content="")

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return tool_call_response if self.calls == 1 else empty_final_response

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        config = {"configurable": {"thread_id": "test-empty-final-after-resume"}}
        state = {"messages": [{"role": "user", "content": "帮家人存一下这个报告"}]}
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="ambiguous",
            confidence="low",
            reason="用户只说家人，没有明确对象。",
            next_action="ask_patient_selection",
        )

        with (
            patch("app.agent.graph.get_openai_llm_stream", return_value=FakeLLM()),
            patch("app.agent.tools.patient.list_subject_candidates", return_value=[]),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            first = await graph.ainvoke(state, config)
            self.assertIn("__interrupt__", first)

            resumed = await graph.ainvoke(Command(resume={"value": "mother", "label": "妈妈"}), config)

        self.assertNotEqual(resumed["metadata"]["status"], "completed")
        self.assertEqual(resumed["metadata"]["status"], "llm_empty_response")
        self.assertEqual(resumed.get("response"), "")

    async def test_graph_returns_error_when_tool_chain_never_produces_final_assistant_answer(self) -> None:
        tool_call_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_health_records_tool",
                    "args": {"subject_id": "subject-mother", "record_type": "physical_exam"},
                    "id": "call_query_records_no_final",
                }
            ],
        )

        class FakeBoundLLM:
            async def ainvoke(self, messages):
                return tool_call_response

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        with patch("app.agent.graph.get_openai_llm_stream", return_value=FakeLLM()):
            result = await graph.ainvoke(
                {
                    "messages": [{"role": "user", "content": "查一下我妈的体检报告"}],
                    "current_subject": {"subject_id": "subject-mother", "display_name": "妈妈", "patient_type": "human"},
                    "subject_resolution_status": "resolved",
                    "subject_resolution_turn_key": "查一下我妈的体检报告",
                },
                {"configurable": {"thread_id": "test-tool-chain-without-final-answer"}},
            )

        self.assertEqual(result["metadata"]["status"], "final_answer_missing")
        self.assertEqual(result.get("response"), "")

    async def test_graph_generates_final_answer_after_capability_missing_tool_result(self) -> None:
        query_tool_call = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_health_records_tool",
                    "args": {"subject_id": "subject-mother", "record_type": "physical_exam"},
                    "id": "call_query_records",
                }
            ],
        )
        final_response = AIMessage(content="已确认对象是妈妈，但当前报告查询工具尚未接入。")

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return query_tool_call if self.calls == 1 else final_response

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        fake_llm = FakeLLM()

        with patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm):
            result = await graph.ainvoke(
                {
                    "messages": [{"role": "user", "content": "查一下我妈的体检报告"}],
                    "current_subject": {"subject_id": "subject-mother", "display_name": "妈妈", "patient_type": "human"},
                    "subject_resolution_status": "resolved",
                    "subject_resolution_turn_key": "查一下我妈的体检报告",
                },
                {"configurable": {"thread_id": "test-final-answer-after-capability-missing"}},
            )

        self.assertEqual(fake_llm.bound.calls, 2)
        self.assertEqual(result["metadata"]["status"], "completed")
        self.assertEqual(result["response"], "已确认对象是妈妈，但当前报告查询工具尚未接入。")

    async def test_graph_passes_latest_tool_observation_to_llm_before_final_answer(self) -> None:
        query_tool_call = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_health_records_tool",
                    "args": {"subject_id": "subject-mother", "record_type": "physical_exam"},
                    "id": "call_query_records_observation",
                }
            ],
        )
        final_response = AIMessage(content="已确认对象是妈妈，但当前报告查询工具尚未接入。")

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.calls = 0
                self.seen_observation_on_second_call = False

            async def ainvoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return query_tool_call
                serialized = "\n".join(str(getattr(message, "content", message)) for message in messages)
                self.seen_observation_on_second_call = "报告查询工具尚未接入" in serialized
                return final_response if self.seen_observation_on_second_call else query_tool_call

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        fake_llm = FakeLLM()

        with patch("app.agent.graph.get_openai_llm_stream", return_value=fake_llm):
            result = await graph.ainvoke(
                {
                    "messages": [{"role": "user", "content": "查一下我妈之前的指标"}],
                    "current_subject": {"subject_id": "subject-mother", "display_name": "妈妈", "patient_type": "human"},
                    "subject_resolution_status": "resolved",
                    "subject_resolution_turn_key": "查一下我妈之前的指标",
                },
                {"configurable": {"thread_id": "test-latest-tool-observation-visible"}},
            )

        self.assertTrue(fake_llm.bound.seen_observation_on_second_call)
        self.assertEqual(result["metadata"]["status"], "completed")
        self.assertEqual(result["response"], "已确认对象是妈妈，但当前报告查询工具尚未接入。")

    async def test_graph_does_not_repeat_patient_resolution_after_user_selection(self) -> None:
        tool_call_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "resolve_patient_tool",
                    "args": {"user_text": "看下我妈上次报告"},
                    "id": "call_resolve_patient_repeat_guard",
                }
            ],
        )
        final_response = AIMessage(content="已确认对象是妈妈，但当前还没有报告查询工具。")

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return tool_call_response if self.calls == 1 else final_response

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        config = {"configurable": {"thread_id": "test-repeat-patient-resolution-after-selection"}}
        state = {"messages": [{"role": "user", "content": "看下我妈上次报告"}]}
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="ambiguous",
            confidence="low",
            reason="需要用户确认。",
            next_action="ask_patient_selection",
        )
        mother = _subject("subject-mother", "mother", "妈妈")

        with (
            patch("app.agent.graph.get_openai_llm_stream", return_value=FakeLLM()),
            patch("app.agent.tools.patient.list_subject_candidates", return_value=[mother]),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            first = await graph.ainvoke(state, config)
            self.assertIn("__interrupt__", first)

            resumed = await graph.ainvoke(
                Command(resume={"value": "subject:subject-mother", "label": "妈妈（成员）"}),
                config,
            )

        self.assertNotIn("__interrupt__", resumed)
        self.assertEqual(resumed["metadata"]["status"], "completed")
        self.assertEqual(resumed["response"], "已确认对象是妈妈，但当前还没有报告查询工具。")

    async def test_graph_finishes_after_create_subject_name_interrupt(self) -> None:
        tool_call_response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "resolve_patient_tool",
                    "args": {"user_text": "帮我老公存报告"},
                    "id": "call_resolve_patient",
                }
            ],
        )
        final_response = AIMessage(content="已为老公建档，接下来可以上传报告。")

        class FakeBoundLLM:
            def __init__(self) -> None:
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                return tool_call_response if self.calls == 1 else final_response

        class FakeLLM:
            def __init__(self) -> None:
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        created_subject = type(
            "CreatedSubject",
            (),
            {
                "id": "subject-husband",
                "display_name": "老公",
                "subject_type": "human",
                "legal_name": None,
            },
        )()
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="ambiguous",
            confidence="low",
            reason="用户提到老公但候选列表里没有匹配主体。",
            next_action="ask_patient_selection",
        )
        config = {"configurable": {"thread_id": "test-create-subject-two-step"}}

        with (
            patch("app.agent.graph.get_openai_llm_stream", return_value=FakeLLM()),
            patch("app.agent.tools.patient.list_subject_candidates", return_value=[]),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
            patch("app.agent.tools.patient.create_subject", return_value=created_subject),
        ):
            first = await graph.ainvoke(
                {"messages": [{"role": "user", "content": "帮我老公存报告"}]},
                config,
            )
            self.assertEqual(first["__interrupt__"][0].value["type"], "select_one")

            second = await graph.ainvoke(
                Command(resume={"value": "create_patient", "label": "新建人物"}),
                config,
            )
            self.assertEqual(second["__interrupt__"][0].value["type"], "text_input")

            finished = await graph.ainvoke(Command(resume={"value": "老公"}), config)

        self.assertNotIn("__interrupt__", finished)
        self.assertEqual(finished["response"], "已为老公建档，接下来可以上传报告。")


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_run_result_exposes_structured_events_for_user_process_and_answer(self) -> None:
        result = _to_run_result(
            "thread-1",
            {
                "response": "已确认对象是爸爸。",
                "process_events": [{"step_type": "tool.observation", "text": "已确认这次管理对象是爸爸。"}],
            },
            user_message="帮我爸看报告",
        )

        event_types = [event.event_type for event in result.events]

        self.assertEqual(event_types, ["message.user", "process.group.started", "process.step", "message.assistant.completed"])
        self.assertEqual(result.events[0].content, "帮我爸看报告")
        self.assertEqual(result.events[-1].content, "已确认对象是爸爸。")

    def test_process_group_is_separate_across_interrupt_and_resume_runs(self) -> None:
        first = _to_run_result(
            "thread-1",
            {
                "__interrupt__": [
                    type(
                        "Interrupt",
                        (),
                        {
                            "value": {
                                "type": "select_one",
                                "title": "这次要管理谁或哪只宠物的健康档案？",
                                "description": "我先把健康档案对象对齐。",
                            }
                        },
                    )()
                ],
                "process_events": [{"step_type": "runtime.note", "text": "需要确认本次健康档案的管理对象。"}],
            },
            user_message="帮我存最近报告",
        )
        resumed = _to_run_result(
            "thread-1",
            {
                "response": "已确认对象是爸爸。",
                "process_events": [{"step_type": "tool.observation", "text": "已确认这次管理对象是爸爸。"}],
            },
        )

        first_group = next(event for event in first.events if event.event_type == "process.group.started")
        resumed_group = next(event for event in resumed.events if event.event_type == "process.group.started")

        self.assertEqual(first_group.work_item_type, "subject_resolution")
        self.assertNotEqual(first_group.work_item_id, resumed_group.work_item_id)
        self.assertNotEqual(first_group.id, resumed_group.id)

    def test_resume_run_records_interrupt_resumed_event_in_same_work_item(self) -> None:
        result = _to_run_result(
            "thread-1",
            {
                "response": "已确认对象是爸爸。",
                "process_events": [{"step_type": "tool.observation", "text": "已确认这次管理对象是爸爸。"}],
            },
            resume_decision={"type": "select_one", "value": "subject_dad"},
        )

        resumed_event = next(event for event in result.events if event.event_type == "interrupt.resumed")
        group_event = next(event for event in result.events if event.event_type == "process.group.started")

        self.assertEqual(resumed_event.status, "completed")
        self.assertEqual(resumed_event.work_item_type, "subject_resolution")
        self.assertEqual(resumed_event.work_item_id, group_event.work_item_id)
        self.assertEqual(resumed_event.payload["decision"], {"type": "select_one", "value": "subject_dad"})

    def test_same_process_text_in_different_runs_creates_different_work_items(self) -> None:
        first = _to_run_result(
            "thread-1",
            {
                "response": "已确认对象是爸爸。",
                "process_events": [{"step_type": "tool.observation", "text": "已确认这次管理对象是爸爸。"}],
            },
            run_id="run-1",
        )
        second = _to_run_result(
            "thread-1",
            {
                "response": "已确认对象是爸爸。",
                "process_events": [{"step_type": "tool.observation", "text": "已确认这次管理对象是爸爸。"}],
            },
            run_id="run-2",
        )

        first_group = next(event for event in first.events if event.event_type == "process.group.started")
        second_group = next(event for event in second.events if event.event_type == "process.group.started")
        first_step = next(event for event in first.events if event.event_type == "process.step")
        second_step = next(event for event in second.events if event.event_type == "process.step")

        self.assertNotEqual(first_group.work_item_id, second_group.work_item_id)
        self.assertNotEqual(first_group.id, second_group.id)
        self.assertNotEqual(first_step.id, second_step.id)

    def test_process_events_have_stable_ids_for_frontend_upsert(self) -> None:
        payload = {
            "__interrupt__": [
                type(
                    "Interrupt",
                    (),
                    {
                        "value": {
                            "type": "text_input",
                            "title": "新建人物档案",
                            "description": "请输入这个人物在 Memomed 里展示的名称。",
                        }
                    },
                )()
            ],
            "process_events": [
                {"step_type": "runtime.note", "text": "需要确认本次健康档案的管理对象。"},
                {"step_type": "runtime.note", "text": "需要确认本次健康档案的管理对象。"},
            ],
        }

        result = _to_run_result("thread-1", payload)

        duplicate_text_events = [
            event
            for event in result.events
            if event.event_type == "process.step"
            and event.content == "需要确认本次健康档案的管理对象。"
        ]
        self.assertEqual(len(duplicate_text_events), 1)

    def test_completed_error_response_is_returned_as_process_event_and_message(self) -> None:
        result = _to_run_result(
            "thread-1",
            {
                "response": "新建档案失败：别名“爷爷”已经被其他成员或宠物使用。",
                "process_events": [
                    {"step_type": "tool.error", "text": "新建档案失败：别名“爷爷”已经被其他成员或宠物使用。"}
                ],
            },
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.messages[0].content, "新建档案失败：别名“爷爷”已经被其他成员或宠物使用。")
        self.assertEqual(result.process_events[0]["step_type"], "tool.error")

    def test_process_step_events_include_display_step_type(self) -> None:
        result = _to_run_result(
            "thread-1",
            {
                "response": "已确认对象。",
                "process_events": [
                    {"step_type": "runtime.note", "text": "正在处理你的确认结果。"},
                    {"step_type": "tool.observation", "text": "已确认这次管理对象是妈妈。"},
                    {"step_type": "tool.error", "text": "工具执行失败。"},
                ],
            },
        )

        process_steps = [event for event in result.events if event.event_type == "process.step"]

        self.assertEqual(
            [event.payload["step_type"] for event in process_steps],
            ["runtime.note", "tool.observation", "tool.error"],
        )

    def test_completed_run_without_llm_text_is_error_not_fallback_answer(self) -> None:
        result = _to_run_result(
            "thread-1",
            {
                "response": "",
                "metadata": {"status": "llm_empty_response"},
                "process_events": [{"step_type": "tool.observation", "text": "已确认这次管理对象是我（成员）。"}],
            },
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.messages, [])
        self.assertEqual(result.error, "LLM 没有返回最终回复文本。")
        self.assertNotIn("message.assistant.completed", [event.event_type for event in result.events])

    def test_completed_run_missing_final_answer_is_error_not_completed(self) -> None:
        result = _to_run_result(
            "thread-1",
            {
                "response": "",
                "metadata": {"status": "final_answer_missing"},
                "process_events": [{"step_type": "tool.observation", "text": "报告查询工具尚未接入。"}],
            },
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.messages, [])
        self.assertEqual(result.error, "Agent 工具流程结束后缺少最终回复文本。")
        self.assertNotIn("message.assistant.completed", [event.event_type for event in result.events])

    def test_interrupted_result_keeps_latest_process_event_and_current_interaction(self) -> None:
        result = _to_run_result(
            "thread-1",
            {
                "__interrupt__": [
                    type(
                        "Interrupt",
                        (),
                        {
                            "value": {
                                "type": "text_input",
                                "title": "新建人物档案",
                                "description": "请输入这个人物在 Memomed 里展示的名称。",
                            }
                        },
                    )()
                ],
                "process_events": [
                    {"step_type": "tool.error", "text": "新建档案失败：别名“爷爷”已经被其他成员或宠物使用。"}
                ],
            },
        )

        self.assertEqual(len(result.process_events), 2)
        self.assertEqual(result.process_events[0]["step_type"], "tool.error")
        self.assertEqual(result.process_events[1]["text"], "请输入这个人物在 Memomed 里展示的名称。")

    async def test_start_chat_returns_thread_id_and_result_shape(self) -> None:
        request = ChatRequest(thread_id="runtime-test-thread", message="帮家人存一下这个报告")
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="ambiguous",
            confidence="low",
            reason="用户只说家人，没有明确对象。",
            next_action="ask_patient_selection",
        )

        with (
            patch("app.agent.graph.get_openai_llm_stream") as llm_mock,
            patch("app.agent.tools.patient.list_subject_candidates", return_value=[]),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
            patch("app.agent.runtime.persist_run_result") as persist_mock,
        ):
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
        persist_mock.assert_awaited_once()

    async def test_stream_start_chat_yields_events_before_final_result(self) -> None:
        interaction = {
            "type": "select_one",
            "title": "这次要管理谁或哪只宠物的健康档案？",
            "description": "我先把健康档案对象对齐。",
            "options": [{"label": "妈妈", "value": "subject:mother"}],
            "pending_action": {
                "id": "pa_confirm_patient",
                "type": "confirm_patient",
                "continuation_tool": "commit_patient_selection",
                "candidate_payload": {"original_text": "帮家人存报告"},
            },
        }

        async def fake_astream(*args, **kwargs):
            yield {
                "inspect_tool_result": {
                    "pending_action": interaction["pending_action"],
                    "interaction": interaction,
                    "process_events": [{"step_type": "runtime.note", "text": "需要确认本次健康档案的管理对象。"}],
                }
            }
            yield {"__interrupt__": (type("Interrupt", (), {"value": interaction})(),)}

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result") as persist_mock,
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-test", message="帮家人存报告")
                )
            ]

        event_types = [packet.event.event_type for packet in packets if packet.event]
        event_seqs = [packet.event.seq for packet in packets if packet.event]
        final_result = packets[-1].result

        self.assertEqual(event_types[0], "message.user")
        self.assertIn("process.group.started", event_types)
        self.assertIn("interrupt.requested", event_types)
        self.assertEqual(event_seqs, sorted(event_seqs))
        self.assertEqual(event_seqs[:3], [1, 2, 3])
        self.assertIsNotNone(final_result)
        self.assertEqual(final_result.status, "interrupted")
        persist_mock.assert_awaited_once()

    async def test_stream_start_chat_yields_custom_process_event_before_node_update(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield (
                "custom",
                {
                    "type": "process_step",
                    "step_type": "tool.started",
                    "title": "工具调用",
                    "text": "正在查询家庭成员与宠物档案。",
                    "work_item_type": "subject_resolution",
                },
            )
            yield {
                "final_answer": {
                    "response": "已完成。",
                    "metadata": {"status": "completed"},
                }
            }

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result"),
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-custom-process-test", message="帮我老公存报告")
                )
            ]

        streamed_events = [packet.event for packet in packets if packet.event]
        event_types = [event.event_type for event in streamed_events]
        contents = [event.content for event in streamed_events]
        run_result_index = next(index for index, packet in enumerate(packets) if packet.result)
        custom_step_index = next(
            index
            for index, packet in enumerate(packets)
            if packet.event and packet.event.content == "正在查询家庭成员与宠物档案。"
        )

        self.assertIn("process.group.started", event_types)
        self.assertIn("process.step", event_types)
        self.assertIn("正在查询家庭成员与宠物档案。", contents)
        self.assertLess(custom_step_index, run_result_index)

    async def test_langgraph_tool_node_emits_custom_process_events_while_running_tool(self) -> None:
        grounding = PatientGrounding(
            intent="human_health",
            resolution_status="resolved",
            matched_subject_id="subject-husband",
            patient_code="husband",
            display_name="老公",
            patient_type="human",
            confidence="high",
            reason="用户明确提到老公。",
            next_action="continue",
        )
        candidate = _subject("subject-husband", "husband", "老公")

        class FakeBoundLLM:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "resolve_patient_tool",
                                "args": {"user_text": "帮我老公存报告"},
                                "id": "call_resolve_patient",
                            }
                        ],
                    )
                return AIMessage(content="已确认对象是老公。")

        class FakeLLM:
            def __init__(self):
                self.bound = FakeBoundLLM()

            def bind_tools(self, tools):
                return self.bound

        custom_payloads = []
        with (
            patch("app.agent.graph.get_openai_llm_stream", return_value=FakeLLM()),
            patch("app.agent.tools.patient.list_subject_candidates", return_value=[candidate]),
            patch("app.agent.tools.patient.classify_patient_grounding", return_value=grounding),
        ):
            async for mode, data in graph.astream(
                {"messages": [{"role": "user", "content": "帮我老公存报告"}], "metadata": {}},
                {"configurable": {"thread_id": "graph-custom-tool-stream-test"}},
                stream_mode=["custom", "updates"],
            ):
                if mode == "custom":
                    custom_payloads.append(data)

        custom_texts = [payload.get("text") for payload in custom_payloads]
        self.assertIn("正在调用工具：确认健康档案对象。", custom_texts)
        self.assertTrue(any("老公" in str(text) for text in custom_texts))

    async def test_stream_start_chat_persists_completed_final_result(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield {
                "final_answer": {
                    "response": "现在还没有接入用药查询工具。",
                    "metadata": {"status": "completed"},
                }
            }

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result") as persist_mock,
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-completed-test", message="帮我看下上次吃的药")
                )
            ]

        final_result = packets[-1].result
        event_types = [event.event_type for event in final_result.events]

        self.assertEqual(final_result.status, "completed")
        self.assertIn("message.user", event_types)
        self.assertIn("message.assistant.completed", event_types)
        persist_mock.assert_awaited_once_with(final_result, trigger_type="user_message")

    async def test_stream_does_not_emit_continuation_tool_result_as_final_answer(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield {
                "continue_pending_action": {
                    "process_events": [{"step_type": "tool.observation", "text": "已新建人物档案：奶奶。"}],
                    "response": "已新建人物档案：奶奶。",
                    "handoff_context": "已新建人物档案：奶奶。",
                    "metadata": {"status": "success"},
                }
            }
            yield {
                "final_answer": {
                    "response": "已为奶奶建档。现在可以上传报告，我会继续帮你整理。",
                    "metadata": {"status": "completed"},
                }
            }

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result"),
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-continuation-test", message="帮我奶奶存报告")
                )
            ]

        streamed_assistant_messages = [
            packet.event.content
            for packet in packets[:-1]
            if packet.event and packet.event.event_type == "message.assistant.completed"
        ]

        self.assertEqual(
            streamed_assistant_messages,
            ["已为奶奶建档。现在可以上传报告，我会继续帮你整理。"],
        )
        self.assertEqual(packets[-1].result.messages[0].content, "已为奶奶建档。现在可以上传报告，我会继续帮你整理。")

    async def test_stream_emits_incremental_assistant_delta_before_completed_message(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield ("messages", (AIMessageChunk(content="你好"), {"langgraph_node": "call_model"}))
            yield ("messages", (AIMessageChunk(content="呀"), {"langgraph_node": "call_model"}))
            yield (
                "updates",
                {
                    "call_model": {
                        "messages": [AIMessage(content="你好呀")],
                        "response": "你好呀",
                    }
                },
            )
            yield (
                "updates",
                {
                    "final_answer": {
                        "response": "你好呀",
                        "metadata": {"status": "completed"},
                    }
                },
            )

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result"),
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-delta-test", message="你好")
                )
            ]

        delta_events = [
            packet.event
            for packet in packets
            if packet.event and packet.event.event_type == "message.assistant.delta"
        ]
        completed_events = [
            packet.event
            for packet in packets
            if packet.event and packet.event.event_type == "message.assistant.completed"
        ]

        self.assertEqual([event.content for event in delta_events], ["你好", "呀"])
        self.assertEqual(len({event.id for event in delta_events}), 2)
        self.assertEqual([event.payload["delta_index"] for event in delta_events], [1, 2])
        self.assertEqual(len({event.payload["message_id"] for event in delta_events}), 1)
        self.assertEqual(completed_events[0].content, "你好呀")
        self.assertEqual(packets[-1].result.messages[0].content, "你好呀")

    async def test_stream_smooths_large_provider_chunks_into_smaller_visible_deltas(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield ("messages", (AIMessageChunk(content="abcdefg"), {"langgraph_node": "call_model"}))
            yield (
                "updates",
                {
                    "call_model": {
                        "messages": [AIMessage(content="abcdefg")],
                        "response": "abcdefg",
                    }
                },
            )
            yield (
                "updates",
                {
                    "final_answer": {
                        "response": "abcdefg",
                        "metadata": {"status": "completed"},
                    }
                },
            )

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result"),
            patch("app.agent.runtime.DISPLAY_DELTA_DELAY_SECONDS", 0),
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-smoothed-delta-test", message="测试流式")
                )
            ]

        delta_events = [
            packet.event
            for packet in packets
            if packet.event and packet.event.event_type == "message.assistant.delta"
        ]

        self.assertEqual([event.content for event in delta_events], ["abc", "def", "g"])
        self.assertEqual([event.payload["offset"] for event in delta_events], [3, 6, 7])

    async def test_stream_hides_preface_text_when_call_model_finishes_with_tool_call(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield ("messages", (AIMessageChunk(content="好的，我先确认一下对象。"), {"langgraph_node": "call_model"}))
            yield (
                "updates",
                {
                    "call_model": {
                        "messages": [
                            AIMessage(
                                content="好的，我先确认一下对象。",
                                tool_calls=[
                                    {
                                        "name": "resolve_patient_tool",
                                        "args": {"user_text": "帮我老公存报告"},
                                        "id": "call_resolve_patient",
                                    }
                                ],
                            )
                        ],
                        "response": "好的，我先确认一下对象。",
                    }
                },
            )

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result"),
            patch("app.agent.runtime.DISPLAY_DELTA_DELAY_SECONDS", 0),
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-preface-hidden-test", message="帮我老公存报告")
                )
            ]

        event_types = [packet.event.event_type for packet in packets if packet.event]
        self.assertNotIn("message.assistant.delta", event_types)
        self.assertNotIn("message.assistant.completed", event_types)

    async def test_stream_hides_tool_preface_even_after_process_events_exist(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield (
                "updates",
                {
                    "continue_pending_action": {
                        "process_events": [{"step_type": "tool.observation", "text": "已确认这次管理对象是妈妈（成员）。"}],
                        "response": "已确认这次管理对象是妈妈（成员）。",
                        "handoff_context": "已确认这次管理对象是妈妈（成员）。",
                        "current_subject": {"subject_id": "subject-mother", "display_name": "妈妈"},
                        "subject_resolution_status": "resolved",
                    }
                },
            )
            yield ("messages", (AIMessageChunk(content="我来帮您查询妈妈的血常规数据。"), {"langgraph_node": "call_model"}))
            yield (
                "updates",
                {
                    "call_model": {
                        "messages": [
                            AIMessage(
                                content="我来帮您查询妈妈的血常规数据。",
                                tool_calls=[
                                    {
                                        "name": "query_health_records_tool",
                                        "args": {"subject_id": "subject-mother", "record_type": "blood_routine"},
                                        "id": "call_query_records",
                                    }
                                ],
                            )
                        ],
                        "response": "我来帮您查询妈妈的血常规数据。",
                    }
                },
            )
            yield (
                "custom",
                {
                    "type": "process_step",
                    "step_type": "tool.observation",
                    "title": "工具结果",
                    "text": "已确认健康档案对象，但报告查询工具尚未接入。",
                    "work_item_type": "subject_resolution",
                },
            )

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result"),
            patch("app.agent.runtime.DISPLAY_DELTA_DELAY_SECONDS", 0),
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-preface-after-process-test", message="帮我看妈妈血常规")
                )
            ]

        delta_contents = [
            packet.event.content
            for packet in packets
            if packet.event and packet.event.event_type == "message.assistant.delta"
        ]

        self.assertEqual(delta_contents, [])

    async def test_stream_ignores_whitespace_only_assistant_chunks(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield ("messages", (AIMessageChunk(content="\n\n\n"), {"langgraph_node": "call_model"}))
            yield ("messages", (AIMessageChunk(content="你好"), {"langgraph_node": "call_model"}))
            yield (
                "updates",
                {
                    "call_model": {
                        "messages": [AIMessage(content="\n\n\n你好")],
                        "response": "\n\n\n你好",
                    }
                },
            )

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result"),
            patch("app.agent.runtime.DISPLAY_DELTA_DELAY_SECONDS", 0),
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-whitespace-delta-test", message="你好")
                )
            ]

        delta_contents = [
            packet.event.content
            for packet in packets
            if packet.event and packet.event.event_type == "message.assistant.delta"
        ]

        self.assertEqual(delta_contents, ["你好"])

    async def test_stream_ignores_tool_call_message_chunks_for_visible_delta(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield (
                "messages",
                (
                    AIMessageChunk(
                        content="",
                        tool_call_chunks=[{"name": "resolve_patient_tool", "args": "{}", "id": "call_1"}],
                    ),
                    {"langgraph_node": "call_model"},
                ),
            )
            yield {
                "final_answer": {
                    "response": "已完成。",
                    "metadata": {"status": "completed"},
                }
            }

        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result"),
        ):
            packets = [
                packet
                async for packet in stream_start_chat(
                    ChatRequest(thread_id="stream-runtime-tool-chunk-test", message="帮我看报告")
                )
            ]

        event_types = [packet.event.event_type for packet in packets if packet.event]
        self.assertNotIn("message.assistant.delta", event_types)


class AgentStreamingRouteTests(unittest.TestCase):
    def test_sse_event_formats_named_json_payload(self) -> None:
        payload = {"id": "evt_1", "event_type": "message.user", "content": "帮我存报告"}

        chunk = _sse_event("agent_event", payload)

        self.assertTrue(chunk.startswith("event: agent_event\n"))
        self.assertIn('"event_type":"message.user"', chunk)
        self.assertTrue(chunk.endswith("\n\n"))

    def test_stream_headers_disable_proxy_buffering(self) -> None:
        headers = _stream_headers()

        self.assertEqual(headers["Cache-Control"], "no-cache")
        self.assertEqual(headers["X-Accel-Buffering"], "no")


if __name__ == "__main__":
    unittest.main()

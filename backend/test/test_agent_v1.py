import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.api.schemas import ChatRequest
from app.agent.graph import graph
from app.agent.hitl.schemas import InteractionRequest, SelectOption
from app.agent.runtime import _to_run_result, start_chat
from app.agent.tools.patient import (
    PatientGrounding,
    SubjectCandidate,
    _selection_options,
    commit_patient_selection,
    resolve_patient_tool,
)
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


class AgentGraphTests(unittest.IsolatedAsyncioTestCase):
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
                "process_events": [{"type": "tool_result", "text": "已确认这次管理对象是爸爸。"}],
            },
            user_message="帮我爸看报告",
        )

        event_types = [event.event_type for event in result.events]

        self.assertEqual(event_types, ["message.user", "process.group.started", "process.step", "message.assistant.completed"])
        self.assertEqual(result.events[0].content, "帮我爸看报告")
        self.assertEqual(result.events[-1].content, "已确认对象是爸爸。")

    def test_process_events_share_work_item_across_interrupt_and_resume_runs(self) -> None:
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
                "process_events": [{"type": "thinking", "text": "需要确认本次健康档案的管理对象。"}],
            },
            user_message="帮我存最近报告",
        )
        resumed = _to_run_result(
            "thread-1",
            {
                "response": "已确认对象是爸爸。",
                "process_events": [{"type": "tool_result", "text": "已确认这次管理对象是爸爸。"}],
            },
        )

        first_group = next(event for event in first.events if event.event_type == "process.group.started")
        resumed_group = next(event for event in resumed.events if event.event_type == "process.group.started")

        self.assertEqual(first_group.work_item_type, "subject_resolution")
        self.assertEqual(first_group.work_item_id, resumed_group.work_item_id)
        self.assertNotEqual(first_group.id, resumed_group.id)

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
                {"type": "thinking", "text": "需要确认本次健康档案的管理对象。"},
                {"type": "thinking", "text": "需要确认本次健康档案的管理对象。"},
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
                    {"type": "error", "text": "新建档案失败：别名“爷爷”已经被其他成员或宠物使用。"}
                ],
            },
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.messages[0].content, "新建档案失败：别名“爷爷”已经被其他成员或宠物使用。")
        self.assertEqual(result.process_events[0]["type"], "error")

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
                    {"type": "error", "text": "新建档案失败：别名“爷爷”已经被其他成员或宠物使用。"}
                ],
            },
        )

        self.assertEqual(len(result.process_events), 2)
        self.assertEqual(result.process_events[0]["type"], "error")
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


if __name__ == "__main__":
    unittest.main()

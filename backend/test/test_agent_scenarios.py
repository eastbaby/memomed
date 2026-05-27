import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, AIMessageChunk

from app.agent.api.schemas import AgentEvent, ChatRequest, ResumeRequest
from app.agent.events.emitter import AgentEventStreamBuffer
from app.agent.runtime import stream_start_chat
from test.agent_scenario_harness import (
    FakeScriptedLLM,
    ScenarioEventStore,
    ScenarioRunner,
    SubjectFixture,
    collect_stream_with_store,
    summarize_events,
)


class AgentScenarioGoldenTests(unittest.IsolatedAsyncioTestCase):
    def test_stream_buffer_keeps_emitted_process_groups_and_steps(self) -> None:
        group = AgentEvent(
            id="evt_run_0003",
            conversation_id="scenario-agent-event-buffer",
            turn_id="turn-1",
            run_id="run-1",
            work_item_id="wi-1",
            work_item_type="health_records_query",
            ordinal=3,
            seq=None,
            event_type="process.group.started",
            role="assistant",
            visibility="collapsed",
            status="streaming",
            title="查询健康报告",
            content="正在调用工具：查询健康报告。",
            payload={"default_expanded": False},
        )
        step = AgentEvent(
            id="evt_run_0004",
            conversation_id="scenario-agent-event-buffer",
            turn_id="turn-1",
            run_id="run-1",
            work_item_id="wi-1",
            work_item_type="health_records_query",
            ordinal=4,
            seq=None,
            event_type="process.step",
            role="tool",
            visibility="collapsed",
            status="completed",
            title="工具结果",
            content="已确认健康档案对象，但报告查询工具尚未接入。",
            payload={"step_type": "tool.observation", "runtime_event_id": "runtime-event-1"},
        )
        buffer = AgentEventStreamBuffer()

        buffer.append(group)
        buffer.append(step)

        self.assertEqual(buffer.events(), [group, step])

    async def test_report_query_hitl_resume_finishes_with_natural_answer(self) -> None:
        llm = FakeScriptedLLM(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "resolve_patient_tool",
                            "args": {"user_text": "查报告"},
                            "id": "call_resolve_patient",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "query_health_records_tool",
                            "args": {"record_type": "physical_exam"},
                            "id": "call_query_records",
                        }
                    ],
                ),
                AIMessage(content="妈妈的健康报告查询功能目前尚未接入，暂时无法直接查看报告。"),
            ]
        )
        store = ScenarioEventStore()
        runner = ScenarioRunner(
            llm=llm,
            event_store=store,
            subjects=[SubjectFixture(subject_id="subject-mother", patient_code="mother", display_name="妈妈")],
        )

        start = await runner.stream_start(ChatRequest(thread_id="scenario-report-hitl", message="查报告"))
        resume = await runner.stream_resume(
            ResumeRequest(
                thread_id="scenario-report-hitl",
                decision={"value": "subject:subject-mother", "label": "妈妈（成员）"},
            )
        )

        history = store.events("scenario-report-hitl")
        summary = summarize_events(history)

        self.assertEqual(start.result.status, "interrupted")
        self.assertEqual(resume.result.status, "completed")
        self.assertEqual(llm.bound_call_count, 3)
        start_live_subject_step_ids = {
            event.id
            for event in start.live_events
            if event.event_type == "process.step" and event.work_item_type == "subject_resolution"
        }
        start_history_subject_step_ids = {
            event.id
            for event in history
            if event.run_id == start.result.events[0].run_id
            and event.event_type == "process.step"
            and event.work_item_type == "subject_resolution"
        }
        self.assertTrue(start_live_subject_step_ids)
        self.assertTrue(start_live_subject_step_ids.issubset(start_history_subject_step_ids))
        resume_live_resumed = next(event for event in resume.live_events if event.event_type == "interrupt.resumed")
        resume_history_resumed = next(
            event
            for event in history
            if event.run_id == resume.result.events[0].run_id and event.event_type == "interrupt.resumed"
        )
        self.assertEqual(resume_history_resumed.id, resume_live_resumed.id)
        self.assertEqual(resume_history_resumed.ordinal, resume_live_resumed.ordinal)
        self.assertEqual(
            summary,
            [
                "001 message.user: 查报告",
                "002 run.elapsed",
                "003 process.group.started[agent_progress]: Agent 过程",
                "004 process.step[agent_progress/agent.progress]: 正在理解需求并选择合适的工具。",
                "005 process.group.started[subject_resolution]: 确认健康档案对象",
                "006 process.step[subject_resolution/tool.started]: 正在调用工具：确认健康档案对象。",
                "007 process.step[subject_resolution/tool.observation]: 需要确认本次健康档案的管理对象。",
                "008 process.step[subject_resolution/runtime.note]: 需要确认本次健康档案的管理对象。",
                "009 interrupt.requested: 这次要管理谁或哪只宠物的健康档案？",
                "010 run.elapsed",
                "011 interrupt.resumed: 用户已确认",
                "012 process.group.started[subject_resolution]: 确认健康档案对象",
                "013 process.step[subject_resolution/runtime.note]: 正在处理你的确认结果。",
                "014 process.step[subject_resolution/tool.observation]: 已确认这次管理对象是妈妈（成员）。",
                "015 process.group.started[health_records_query]: 查询健康报告",
                "016 process.step[health_records_query/tool.started]: 正在调用工具：查询健康报告。",
                "017 process.step[health_records_query/tool.observation]: 已确认健康档案对象，但报告查询工具尚未接入。",
                "018 message.assistant.completed: 妈妈的健康报告查询功能目前尚未接入，暂时无法直接查看报告。",
            ],
        )
        self.assertNotEqual(history[-1].content, "已确认健康档案对象，但报告查询工具尚未接入。")

    async def test_runtime_cancels_tool_preface_delta_and_persists_final_timeline(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield ("messages", (AIMessageChunk(content="我先确认一下"), {"langgraph_node": "call_model"}))
            yield {
                "call_model": {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "resolve_patient_tool",
                                    "args": {"user_text": "查报告"},
                                    "id": "call_resolve_patient",
                                }
                            ],
                        )
                    ],
                    "response": "",
                }
            }
            yield (
                "custom",
                {
                    "type": "process_step",
                    "step_type": "tool.started",
                    "title": "工具调用",
                    "text": "正在调用工具：确认健康档案对象。",
                    "work_item_type": "subject_resolution",
                },
            )
            yield {
                "final_answer": {
                    "response": "我已经确认过流程，当前报告查询能力尚未接入。",
                    "metadata": {"status": "completed"},
                }
            }

        store = ScenarioEventStore()
        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result", side_effect=store.persist),
            patch("app.agent.runtime.DISPLAY_DELTA_DELAY_SECONDS", 0),
        ):
            run = await collect_stream_with_store(
                stream_start_chat(ChatRequest(thread_id="scenario-delta-cancel", message="查报告"))
            )

        live_types = [event.event_type for event in run.live_events]
        history_types = [event.event_type for event in store.events("scenario-delta-cancel")]

        self.assertIn("message.assistant.delta", live_types)
        self.assertIn("message.assistant.cancelled", live_types)
        self.assertLess(live_types.index("message.assistant.delta"), live_types.index("message.assistant.cancelled"))
        self.assertNotIn("message.assistant.delta", history_types)
        self.assertNotIn("message.assistant.cancelled", history_types)
        self.assertEqual(history_types[-1], "message.assistant.completed")
        self.assertEqual(run.result.messages[0].content, "我已经确认过流程，当前报告查询能力尚未接入。")

    async def test_streamed_process_steps_keep_same_event_identity_in_history(self) -> None:
        async def fake_astream(*args, **kwargs):
            yield (
                "custom",
                {
                    "type": "process_step",
                    "step_type": "tool.started",
                    "title": "工具调用",
                    "text": "正在调用工具：查询健康报告。",
                    "work_item_type": "health_records_query",
                    "payload": {"runtime_event_id": "runtime-query-started"},
                },
            )
            yield {
                "final_answer": {
                    "response": "报告查询能力尚未接入，我可以先帮你记录需要查询的报告类型。",
                    "metadata": {"status": "completed"},
                }
            }

        store = ScenarioEventStore()
        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result", side_effect=store.persist),
        ):
            run = await collect_stream_with_store(
                stream_start_chat(ChatRequest(thread_id="scenario-process-identity", message="查报告"))
            )

        live_steps = [
            event
            for event in run.live_events
            if event.event_type == "process.step" and event.payload.get("runtime_event_id") == "runtime-query-started"
        ]
        history_steps = [
            event
            for event in store.events("scenario-process-identity")
            if event.event_type == "process.step" and event.content == "正在调用工具：查询健康报告。"
        ]

        self.assertEqual(len(live_steps), 1)
        self.assertEqual(len(history_steps), 1)
        self.assertEqual(history_steps[0].id, live_steps[0].id)
        self.assertEqual(history_steps[0].run_id, live_steps[0].run_id)
        self.assertEqual(history_steps[0].ordinal, live_steps[0].ordinal)
        self.assertEqual(history_steps[0].work_item_type, "health_records_query")

    async def test_multiple_streamed_steps_in_same_work_item_share_original_parent_group(self) -> None:
        async def fake_astream(*args, **kwargs):
            for step_type, text, runtime_event_id in [
                ("tool.started", "正在调用工具：查询健康报告。", "runtime-query-started"),
                ("tool.observation", "已确认健康档案对象，但报告查询工具尚未接入。", "runtime-query-observation"),
            ]:
                yield (
                    "custom",
                    {
                        "type": "process_step",
                        "step_type": step_type,
                        "text": text,
                        "work_item_type": "health_records_query",
                        "payload": {"runtime_event_id": runtime_event_id},
                    },
                )
            yield {
                "final_answer": {
                    "response": "报告查询能力尚未接入。",
                    "metadata": {"status": "completed"},
                }
            }

        store = ScenarioEventStore()
        with (
            patch("app.agent.runtime.graph.astream", side_effect=fake_astream),
            patch("app.agent.runtime.persist_run_result", side_effect=store.persist),
        ):
            run = await collect_stream_with_store(
                stream_start_chat(ChatRequest(thread_id="scenario-process-parent", message="查报告"))
            )

        live_groups = [
            event
            for event in run.live_events
            if event.event_type == "process.group.started" and event.work_item_type == "health_records_query"
        ]
        live_steps = [
            event
            for event in run.live_events
            if event.event_type == "process.step" and event.work_item_type == "health_records_query"
        ]

        self.assertEqual(len(live_groups), 1)
        self.assertEqual(len(live_steps), 2)
        self.assertEqual([event.parent_event_id for event in live_steps], [live_groups[0].id, live_groups[0].id])


if __name__ == "__main__":
    unittest.main()

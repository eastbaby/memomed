import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.api.schemas import AgentEvent, AgentRunResult, ChatMessage
from app.agent.events.service import (
    apply_conversation_seq_offset,
    _event_model,
    _pending_interrupt_completion_statement,
    _run_status_from_result,
    _title_from_events,
    persist_run_result,
)


class AgentEventStoreTests(unittest.IsolatedAsyncioTestCase):
    def test_title_uses_first_user_message(self) -> None:
        events = [
            AgentEvent(
                id="evt_user",
                conversation_id="thread-1",
                run_id="run-1",
                seq=1,
                event_type="message.user",
                role="user",
                content="帮我老公存报告",
            )
        ]

        self.assertEqual(_title_from_events(events), "帮我老公存报告")

    def test_title_falls_back_to_new_conversation(self) -> None:
        self.assertEqual(_title_from_events([]), "新的健康咨询")

    def test_event_model_offsets_seq_for_conversation_timeline(self) -> None:
        event = AgentEvent(
            id="evt_answer",
            conversation_id="thread-1",
            run_id="run-1",
            seq=2,
            event_type="message.assistant.completed",
            role="assistant",
            content="处理完成",
        )

        row = _event_model(event, "thread-1", "run-1", "default", seq_offset=5)

        self.assertEqual(row.seq, 7)

    def test_apply_conversation_seq_offset_updates_events_for_streaming_client(self) -> None:
        result = AgentRunResult(
            thread_id="thread-1",
            status="completed",
            events=[
                AgentEvent(
                    id="evt_user",
                    conversation_id="thread-1",
                    run_id="run-1",
                    seq=1,
                    event_type="message.user",
                    role="user",
                    content="新消息",
                ),
                AgentEvent(
                    id="evt_answer",
                    conversation_id="thread-1",
                    run_id="run-1",
                    seq=2,
                    event_type="message.assistant.completed",
                    role="assistant",
                    content="新回答",
                ),
            ],
        )

        shifted = apply_conversation_seq_offset(result, seq_offset=8)

        self.assertEqual([event.seq for event in shifted.events], [9, 10])
        self.assertEqual([event.seq for event in result.events], [1, 2])

    def test_pending_interrupt_completion_statement_targets_only_pending_interrupts(self) -> None:
        statement = _pending_interrupt_completion_statement("thread-1", "default")
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))

        self.assertIn("UPDATE mm_agent_events", compiled)
        self.assertIn("conversation_id = 'thread-1'", compiled)
        self.assertIn("owner_user_id = 'default'", compiled)
        self.assertIn("event_type = 'interrupt.requested'", compiled)
        self.assertIn("status = 'pending'", compiled)
        self.assertIn("status='completed'", compiled)

    def test_run_status_maps_agent_error_to_failed(self) -> None:
        result = AgentRunResult(thread_id="thread-1", status="error", error="LLM 没有返回最终回复文本。")

        self.assertEqual(_run_status_from_result(result), "failed")

    async def test_persist_run_result_writes_conversation_run_and_events(self) -> None:
        result = AgentRunResult(
            thread_id="thread-1",
            status="completed",
            messages=[ChatMessage(role="assistant", content="处理完成")],
            events=[
                AgentEvent(
                    id="evt_user",
                    conversation_id="thread-1",
                    run_id="run-1",
                    seq=1,
                    event_type="message.user",
                    role="user",
                    content="帮我老公存报告",
                ),
                AgentEvent(
                    id="evt_answer",
                    conversation_id="thread-1",
                    run_id="run-1",
                    seq=2,
                    event_type="message.assistant.completed",
                    role="assistant",
                    content="处理完成",
                ),
            ],
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.merge = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=session)
        context_manager.__aexit__ = AsyncMock(return_value=None)

        with patch("app.agent.events.service.AsyncSessionLocal", return_value=context_manager):
            await persist_run_result(result, trigger_type="user_message")

        self.assertEqual(session.merge.await_count, 4)
        session.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

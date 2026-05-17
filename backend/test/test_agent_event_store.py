import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.api.schemas import AgentEvent, AgentRunResult, ChatMessage
from app.agent.events.service import _event_model, _title_from_events, persist_run_result


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

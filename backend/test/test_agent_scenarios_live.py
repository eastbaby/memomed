import os
import unittest
from uuid import uuid4

from app.agent.api.schemas import ChatRequest, ResumeRequest
from app.agent.llm import get_openai_llm_non_stream
from app.agent.runtime import stream_resume_chat, stream_start_chat
from test.agent_scenario_harness import collect_stream_with_store


@unittest.skipUnless(
    os.getenv("MEMOMED_LIVE_AGENT_SCENARIOS") == "1",
    "set MEMOMED_LIVE_AGENT_SCENARIOS=1 to run live LLM agent scenarios",
)
class LiveAgentScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_report_query_finishes_with_user_facing_capability_missing_answer(self) -> None:
        thread_id = f"live-scenario-{uuid4().hex}"

        start = await collect_stream_with_store(stream_start_chat(ChatRequest(thread_id=thread_id, message="查报告")))
        self.assertEqual(start.result.status, "interrupted")
        interaction = start.result.interrupt
        if not interaction:
            raise AssertionError("live scenario expected a subject-selection interrupt")

        mother_option = next((option for option in interaction.options if "妈妈" in option.label), None)
        if mother_option is None:
            raise unittest.SkipTest("live local subject registry has no 妈妈 option")

        resume = await collect_stream_with_store(
            stream_resume_chat(
                ResumeRequest(
                    thread_id=thread_id,
                    decision={"value": mother_option.value, "label": mother_option.label},
                )
            )
        )

        self.assertEqual(resume.result.status, "completed")
        answer = resume.result.messages[0].content
        self.assertIn("报告", answer)
        self.assertIn("尚未接入", answer)
        self.assertNotEqual(answer.strip(), "已确认健康档案对象，但报告查询工具尚未接入。")

        if os.getenv("MEMOMED_LIVE_AGENT_JUDGE") == "1":
            judgment = await _judge_capability_missing_answer(answer)
            self.assertIn("PASS", judgment)


async def _judge_capability_missing_answer(answer: str) -> str:
    judge = get_openai_llm_non_stream()
    result = await judge.ainvoke(
        [
            {
                "role": "system",
                "content": (
                    "你是测试裁判，只判断一个医疗助手回答是否适合作为用户可见最终回复。"
                    "如果回答自然地说明报告查询能力尚未接入、没有暴露 JSON/工具字段/内部 ID、"
                    "没有机械复读工具过程文本，输出 PASS；否则输出 FAIL 并简短说明。"
                ),
            },
            {"role": "user", "content": answer},
        ]
    )
    return str(getattr(result, "content", result))


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.graph import graph
from app.agent.utils import nodes, rag, tools


class VectorStoreProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        rag._vector_store_provider._store = None

    async def test_get_vector_store_caches_instance(self) -> None:
        store = object()

        with patch.object(rag.PGVectorStore, "create", new=AsyncMock(return_value=store)) as create_mock:
            first = await rag.get_vector_store()
            second = await rag.get_vector_store()

        self.assertIs(first, store)
        self.assertIs(second, store)
        create_mock.assert_awaited_once()


class RagFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_medical_report_orchestrates_prepare_and_store(self) -> None:
        prepared_report = {
            "ocr_pages": [{"page_number": 1, "source_uri": "img://1", "text": "cbc report"}],
            "report_metadata": {
                "patient_code": "self",
                "display_name": "我",
                "patient_type": "human",
                "parse_status": "parsed",
            },
            "source_uri": "img://1",
        }
        stored = {
            "report_id": "r1",
            "patient_code": "self",
            "display_name": "我",
            "parse_status": "parsed",
            "page_count": 1,
            "chunk_count": 2,
        }

        with (
            patch.object(rag, "prepare_medical_report", new=AsyncMock(return_value=prepared_report)) as prepare_mock,
            patch.object(rag, "store_prepared_medical_report", new=AsyncMock(return_value=stored)) as store_mock,
        ):
            result = await rag.process_medical_report("img://1", patient_hint="self")

        prepare_mock.assert_awaited_once_with("img://1", patient_hint="self")
        store_mock.assert_awaited_once_with(prepared_report)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["report_id"], "r1")
        self.assertEqual(result["chunk_count"], 2)


class NodeFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_input_builds_single_report_plan(self) -> None:
        state = {
            "messages": [
                {
                    "content": [
                        {
                            "type": "image",
                            "mimeType": "image/png",
                            "data": "base64data",
                        }
                    ]
                }
            ]
        }

        with patch.object(
            nodes, "_decide_whether_store_image", new=AsyncMock(return_value=["store_pending"])
        ):
            result = await nodes.process_input(state)

        self.assertEqual(result["human_image_store_list"], ["store_pending"])
        self.assertEqual(len(result["report_upload_plans"]), 1)
        self.assertEqual(result["report_upload_plans"][0]["ordered_image_indices"], [1])
        self.assertTrue(result["report_upload_plans"][0]["selected"])

    async def test_graph_ainvoke_runs_async_node_chain_for_single_image(self) -> None:
        state = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "帮我看看这张报告"},
                        {
                            "type": "image",
                            "mimeType": "image/png",
                            "data": "base64data",
                        },
                    ],
                }
            ]
        }
        config = {"configurable": {"thread_id": "single-image-thread"}}
        llm_response = AIMessage(content="这是报告的简要解读")
        prepared_report = {
            "ocr_pages": [{"page_number": 1, "source_uri": "img://1", "text": "cbc report"}],
            "report_metadata": {
                "patient_code": "self",
                "display_name": "我",
                "patient_type": "human",
                "parse_status": "parsed",
            },
            "source_uri": "img://1",
        }
        store_result = {
            "report_id": "r1",
            "patient_code": "self",
            "display_name": "我",
            "parse_status": "parsed",
            "page_count": 1,
            "chunk_count": 2,
        }

        class _FakeBoundLLM:
            async def ainvoke(self, messages):
                return llm_response

        class _FakeLLM:
            def bind_tools(self, tool_list):
                return _FakeBoundLLM()

        with (
            patch.object(nodes, "_decide_whether_store_image", new=AsyncMock(return_value=["store_pending"])),
            patch.object(nodes, "prepare_medical_report", new=AsyncMock(return_value=prepared_report)),
            patch.object(nodes, "store_prepared_medical_report", new=AsyncMock(return_value=store_result)),
            patch.object(nodes, "_extract_answer_keypoints", new=AsyncMock(return_value=["概括报告结论"])),
            patch.object(nodes, "get_openai_llm_stream", return_value=_FakeLLM()),
            patch.object(nodes, "get_tools", return_value=[]),
        ):
            result = await graph.ainvoke(state, config)

        self.assertEqual(result["response"], "这是报告的简要解读")
        self.assertEqual(result["metadata"]["status"], "completed")
        self.assertTrue(
            any(
                "系统已自动存储图片1到数据库中" in message.content
                for message in result["messages"]
                if isinstance(message, AIMessage)
            )
        )

    async def test_graph_interrupts_for_multi_image_confirmation(self) -> None:
        state = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "把这两张报告存一下"},
                        {"type": "image", "mimeType": "image/png", "data": "img1"},
                        {"type": "image", "mimeType": "image/png", "data": "img2"},
                    ],
                }
            ]
        }
        config = {"configurable": {"thread_id": "multi-image-thread"}}
        planned_groups = [
            {
                "group_id": "report_1",
                "image_indices": [1, 2],
                "ordered_image_indices": [2, 1],
                "report_type": "血常规",
                "patient_hint": "mother",
                "reasoning": "第2张像首页，第1张像续页。",
                "needs_confirmation": True,
                "selected": None,
            }
        ]

        with (
            patch.object(nodes, "_decide_whether_store_image", new=AsyncMock(return_value=["store_pending", "store_pending"])),
            patch.object(nodes, "_plan_report_uploads", new=AsyncMock(return_value=planned_groups)),
        ):
            result = await graph.ainvoke(state, config)

        self.assertIn("__interrupt__", result)
        interrupt_payload = result["__interrupt__"][0].value
        self.assertEqual(interrupt_payload["type"], "confirm_report_uploads")
        self.assertEqual(interrupt_payload["groups"][0]["ordered_image_indices"], [2, 1])

    async def test_graph_interrupts_on_needs_confirm_and_resumes_to_store(self) -> None:
        state = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "存一下这张体检报告"},
                        {"type": "image", "mimeType": "image/png", "data": "img1"},
                    ],
                }
            ]
        }
        config = {"configurable": {"thread_id": "needs-confirm-thread"}}
        llm_response = AIMessage(content="报告已经帮你整理好了")
        prepared_report = {
            "ocr_pages": [{"page_number": 1, "source_uri": "img://1", "text": "report text"}],
            "report_metadata": {
                "patient_code": "other",
                "display_name": "家庭成员",
                "patient_type": "human",
                "relation_type": "other",
                "report_type": None,
                "parse_status": "needs_confirm",
                "parse_notes": "归属人和报告类型不够确定",
            },
            "source_uri": "img://1",
        }
        store_result = {
            "report_id": "r2",
            "patient_code": "mother",
            "display_name": "妈妈",
            "parse_status": "parsed",
            "page_count": 1,
            "chunk_count": 2,
        }

        class _FakeBoundLLM:
            async def ainvoke(self, messages):
                return llm_response

        class _FakeLLM:
            def bind_tools(self, tool_list):
                return _FakeBoundLLM()

        with (
            patch.object(nodes, "_decide_whether_store_image", new=AsyncMock(return_value=["store_pending"])),
            patch.object(nodes, "prepare_medical_report", new=AsyncMock(return_value=prepared_report)),
            patch.object(nodes, "store_prepared_medical_report", new=AsyncMock(return_value=store_result)) as store_mock,
            patch.object(nodes, "get_openai_llm_stream", return_value=_FakeLLM()),
            patch.object(nodes, "get_tools", return_value=[]),
        ):
            first = await graph.ainvoke(state, config)
            self.assertIn("__interrupt__", first)
            payload = first["__interrupt__"][0].value
            self.assertEqual(payload["type"], "confirm_report_metadata")

            resumed = await graph.ainvoke(
                Command(
                    resume={
                        "confirmed": True,
                        "reports": [
                            {
                                "group_id": "report_1",
                                "metadata": {
                                    "patient_code": "mother",
                                    "display_name": "妈妈",
                                    "report_type": "体检报告",
                                },
                            }
                        ],
                    }
                ),
                config,
            )

        store_mock.assert_awaited_once()
        self.assertEqual(resumed["response"], "报告已经帮你整理好了")
        self.assertEqual(resumed["human_image_store_list"], ["store_success"])


class ToolFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_medical_reports_formats_async_results(self) -> None:
        docs = [
            Document(
                page_content="血常规结果正常",
                metadata={
                    "report_type": "血常规",
                    "page_number": 1,
                    "hospital_name": "协和医院",
                },
            )
        ]

        with patch.object(tools, "search_report_chunks", new=AsyncMock(return_value=docs)) as search_mock:
            result = await tools.search_medical_reports.ainvoke(
                {"query": "血常规", "patient_hint": "self", "report_type": "血常规"}
            )

        search_mock.assert_awaited_once_with(
            query="血常规",
            patient_code="self",
            report_type="血常规",
        )
        self.assertIn("内容: 血常规结果正常", result)
        self.assertIn("报告类型: 血常规", result)


if __name__ == "__main__":
    unittest.main()

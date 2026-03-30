import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
from langchain_core.documents import Document

from app.agent.utils import nodes, rag, tools
from app.agent.graph import graph


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
    async def test_process_medical_report_orchestrates_async_steps(self) -> None:
        pages = [{"page_number": 1, "source_uri": "img://1", "text": "cbc report"}]
        metadata = rag.ReportMetadata(
            patient_code="self",
            display_name="我",
            patient_type="human",
            parse_status="parsed",
        )
        stored = {
            "report_id": "r1",
            "patient_code": "self",
            "display_name": "我",
            "parse_status": "parsed",
            "page_count": 1,
            "chunk_count": 2,
        }

        with (
            patch.object(rag, "extract_report_pages", new=AsyncMock(return_value=pages)) as pages_mock,
            patch.object(rag, "extract_report_metadata", new=AsyncMock(return_value=metadata)) as metadata_mock,
            patch.object(rag, "store_report_and_chunks", new=AsyncMock(return_value=stored)) as store_mock,
        ):
            result = await rag.process_medical_report("img://1", patient_hint="self")

        pages_mock.assert_awaited_once_with("img://1")
        metadata_mock.assert_awaited_once_with(pages, patient_hint="self")
        store_mock.assert_awaited_once_with(pages, metadata, source_uri="img://1")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["report_id"], "r1")
        self.assertEqual(result["chunk_count"], 2)


class NodeFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_input_awaits_report_storage(self) -> None:
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

        with (
            patch.object(nodes, "_decide_whether_store_image", new=AsyncMock(return_value=["store_pending"])) as decide_mock,
            patch.object(nodes, "process_medical_report", new=AsyncMock(return_value={"status": "success"})) as process_mock,
        ):
            result = await nodes.process_input(state)

        decide_mock.assert_awaited_once()
        process_mock.assert_awaited_once()
        self.assertEqual(result["human_image_store_list"], ["store_success"])
        self.assertIn("系统已自动存储图片1到数据库中", result["messages"][0].content)

    async def test_graph_ainvoke_runs_async_node_chain(self) -> None:
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

        llm_response = AIMessage(content="这是报告的简要解读")

        class _FakeBoundLLM:
            async def ainvoke(self, messages):
                return llm_response

        class _FakeLLM:
            def bind_tools(self, tool_list):
                return _FakeBoundLLM()

        with (
            patch.object(nodes, "_decide_whether_store_image", new=AsyncMock(return_value=["store_pending"])),
            patch.object(nodes, "process_medical_report", new=AsyncMock(return_value={"status": "success"})),
            patch.object(nodes, "_extract_answer_keypoints", new=AsyncMock(return_value=["概括报告结论"])),
            patch.object(nodes, "get_openai_llm_stream", return_value=_FakeLLM()),
            patch.object(nodes, "get_tools", return_value=[]),
        ):
            result = await graph.ainvoke(state)

        self.assertEqual(result["response"], "这是报告的简要解读")
        self.assertEqual(result["metadata"]["status"], "completed")
        self.assertIn("answer_keypoints", result["metadata"])
        self.assertTrue(any("系统已自动存储图片1到数据库中" in message.content for message in result["messages"] if isinstance(message, AIMessage)))


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

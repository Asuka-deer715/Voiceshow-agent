import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import agent_nodes, graph, rag
from app.knowledge_ingestion import import_collection, split_long_text


class KnowledgeImportTests(unittest.TestCase):
    def test_import_preserves_qa_sources_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            original = "产品FAQ v1\n产品部\n\nQ1: 文档额度是多少？\nA: 最多50个。\n\nQ2: 支持PDF吗？\nA: 支持PDF。\n"
            (source / "faq.txt").write_text(original, encoding="utf-8")
            first = import_collection(source, root / "knowledge", "sample")
            chunk_path = root / "knowledge" / "sample" / "chunks.jsonl"
            before = chunk_path.read_bytes()
            second = import_collection(source, root / "knowledge", "sample")
            self.assertEqual(before, chunk_path.read_bytes())
            self.assertEqual(first["chunk_count"], second["chunk_count"])
            self.assertEqual((source / "faq.txt").read_text(encoding="utf-8"), original)
            chunks = [json.loads(line) for line in before.decode("utf-8").splitlines()]
            answer = next(chunk for chunk in chunks if chunk["heading"].startswith("Q1"))
            self.assertIn("A: 最多50个。", answer["text"])
            self.assertNotIn("Q2", answer["text"])
            self.assertEqual(answer["source"], "faq.txt")

    def test_long_sections_are_bounded_and_keep_end_of_text(self):
        parts = split_long_text("资料正文" * 800)
        self.assertTrue(all(len(part) <= 1000 for part in parts))
        self.assertTrue(parts[-1].endswith("资料正文"))


class ReferenceRetrievalTests(unittest.TestCase):
    def test_product_faq_and_technical_spec_are_retrievable(self):
        for query, source, evidence in [
            ("免费版知识库最多支持多少个文档？", "product-faq.txt", "最多50个"),
            ("Commit Message提交规范是什么？", "tech-spec.txt", "type(scope): message"),
        ]:
            with self.subTest(query=query):
                result = rag.retrieve(query)[0]
                self.assertEqual(result["source"], source)
                self.assertIn(evidence, result["text"])

    def test_explicit_source_prevents_cross_handbook_results(self):
        results = rag.retrieve("hr-handbook.txt 年假怎么申请？")
        self.assertTrue(results)
        self.assertTrue(all(item["source"] == "hr-handbook.txt" for item in results))
        self.assertIn("提前3个工作日", results[0]["text"])

    def test_pdf_evidence_has_page_citation(self):
        results = rag.retrieve("每月几天远程办公", collection="jc_ai", source="policy.pdf")
        self.assertIn("4天远程办公", results[0]["text"])
        self.assertEqual(results[0]["page"], 5)
        self.assertIn("policy.pdf / page 5", rag.assemble_context(results))

    def test_knowledge_questions_do_not_request_shopping_slots(self):
        for query in ("免费版有没有API权限？", "试用期多长？", "员工手册中年假怎么申请？"):
            self.assertEqual(graph.fallback_intent(query), "knowledge_query")
        state = {"intent": "knowledge_query", "session": {"slots": {"category": "跑鞋"}}, "trace": []}
        with patch("app.llm.extract_slots") as extract:
            result = agent_nodes.extract_slots(state)
        extract.assert_not_called()
        self.assertEqual(result["slots"], {"category": "跑鞋"})

    def test_document_question_runs_through_graph_without_network(self):
        with patch("app.llm.configured", return_value=False), \
             patch("app.db.get_session", return_value={"slots": {}, "phase": "INTENT"}), \
             patch("app.db.recent_messages", return_value=[]), \
             patch("app.db.append_message"), patch("app.db.save_session"), patch("app.db.save_trace"):
            result = graph.run_agent("免费版知识库最多支持多少个文档？", session_id="reference-test")
        self.assertIn("product-faq.txt", result["sources"])
        self.assertIn("最多50个", result["response"])
        self.assertEqual(result["recommendations"], [])
        self.assertIn("rag_retrieve", [event["node"] for event in result["trace"]])


if __name__ == "__main__":
    unittest.main()

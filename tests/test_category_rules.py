import unittest

from app import graph


class CategoryRuleTests(unittest.TestCase):
    def test_supported_running_shoes_are_still_recognized(self) -> None:
        self.assertEqual(graph.extract_slots("我想买适合跑步的鞋")["category"], graph.RUN_SHOE)
        self.assertEqual(graph.extract_slots("有跑鞋吗")["category"], graph.RUN_SHOE)

    def test_specific_unsupported_shoes_are_not_mapped_to_running_shoes(self) -> None:
        for query, category in [
            ("有休闲鞋吗", "休闲鞋"),
            ("你们有皮鞋吗？", "皮鞋"),
            ("给我推荐篮球鞋", "篮球鞋"),
            ("想买高跟鞋", "高跟鞋"),
        ]:
            with self.subTest(query=query):
                self.assertEqual(graph.unsupported_category_from_text(query), category)
                self.assertIsNone(graph.extract_slots(query)["category"])

    def test_generic_shoes_do_not_silently_become_running_shoes(self) -> None:
        self.assertIsNone(graph.extract_slots("我想买双鞋")["category"])
        self.assertIsNone(graph.extract_slots("今天想买个鞋子")["category"])

    def test_availability_question_is_detected(self) -> None:
        self.assertEqual(graph.fallback_intent("有休闲鞋吗"), "product_availability_query")


if __name__ == "__main__":
    unittest.main()

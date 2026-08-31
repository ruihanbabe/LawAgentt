from __future__ import annotations

import unittest
from datetime import date
from lawagent_evaluation.joint_retrieval import QueryCaseLabels, QueryLegalGold, callback_from_cases, compact_query_text, label_match_score, label_weighted_rerank, legal_metrics, reconstruct_case_text
from lawagent_evaluation.legal_basis_callback import LawCatalog, LawRecord, LegalCitation, canonical_law_title, normalize_article_no


def law_record(chunk_id: str, title: str, article_no: str, start: date | None = None, end: date | None = None) -> LawRecord:
    return LawRecord(chunk_id, title, article_no, "条文", start, end, {})


class JointRetrievalTest(unittest.TestCase):
    def test_normalizes_chinese_article_and_suffix(self) -> None:
        self.assertEqual(normalize_article_no("第一百二十条之一"), "120-1")

    def test_malformed_article_number_does_not_abort_batch(self) -> None:
        self.assertIsNone(normalize_article_no("第一四十四条"))

    def test_callback_uses_exact_title_article_and_event_date(self) -> None:
        catalog = LawCatalog([
            law_record("old", "中华人民共和国民法典", "1", date(2020, 1, 1), date(2021, 1, 1)),
            law_record("new", "中华人民共和国民法典", "1", date(2021, 1, 1)),
        ])
        result = catalog.resolve(LegalCitation("《中华人民共和国民法典》", "1"), date(2020, 6, 1))
        self.assertEqual(result.record.chunk_id, "old")

    def test_callback_does_not_guess_unmapped_law(self) -> None:
        result = LawCatalog([]).resolve(LegalCitation("不存在法", "1"))
        self.assertEqual(result.status, "law_not_found")
        self.assertIsNone(result.record)

    def test_canonical_title_normalizes_country_prefix_but_keeps_version(self) -> None:
        self.assertEqual(canonical_law_title("《中华人民共和国民事诉讼法》"), "民事诉讼法")
        self.assertEqual(canonical_law_title("民事诉讼法（2013年）"), "民事诉讼法|version=2013年")

    def test_civil_code_book_title_resolves_from_root_title(self) -> None:
        catalog = LawCatalog([law_record("contract", "中华人民共和国民法典·合同编", "509")])
        result = catalog.resolve(LegalCitation("中华人民共和国民法典", "509"))
        self.assertEqual(result.record.chunk_id, "contract")

    def test_case_callback_and_complementarity_metric(self) -> None:
        catalog = LawCatalog([law_record("law-1", "中华人民共和国民法典", "1")])
        payloads = {"case-1": {"legal_basis": [{"law": "《中华人民共和国民法典》", "terms": "第一条"}]}}
        callbacks = callback_from_cases(["case-1"], payloads, catalog, top_n=1)
        citation = LegalCitation("中华人民共和国民法典", "1")
        gold = QueryLegalGold("q", frozenset({citation}), {citation: 3}, 3)
        metrics = legal_metrics([], callbacks, gold)
        self.assertEqual(metrics["callback_added_query_gold"], 1)
        self.assertEqual(metrics["query_legal_basis_hit"], 1.0)
        self.assertEqual(metrics["consensus_legal_basis_hit"], 1.0)

    def test_reconstructs_the_non_leaking_case_retrieval_view(self) -> None:
        text = reconstruct_case_text({"case_type": "民事案件", "case_causes": ["租赁合同纠纷"], "claims_and_facts": "退还押金", "case_record": "程序套话", "judge_reason": "不应进入"})
        self.assertIn("退还押金", text)
        self.assertIn("案件类型：民事案件", text)
        self.assertTrue(text.startswith("诉请与核心事实：退还押金"))
        self.assertNotIn("程序套话", text)
        self.assertNotIn("不应进入", text)

    def test_compact_query_prioritizes_claims_and_drops_case_record(self) -> None:
        text = compact_query_text("案件类型：民事\n审理程序：一审\n案由：租赁纠纷\n案件经过：程序套话\n诉请与事实：退还押金\n关键词：押金")
        self.assertTrue(text.startswith("诉请与核心事实：退还押金"))
        self.assertNotIn("程序套话", text)
        self.assertIn("案件类型：民事", text)
        self.assertLess(text.index("案由"), text.index("审理程序"))

    def test_label_weighting_prefers_exact_cause_category_and_keywords(self) -> None:
        labels = QueryCaseLabels(frozenset({"房屋租赁合同纠纷"}), "房地产纠纷", "租赁合同", frozenset({"押金", "返还"}))
        payloads = {
            "semantic": {"case_causes": ["车辆租赁合同纠纷"], "category_l1": "合同事务", "category_l2": "租赁合同", "keywords": ["返还"]},
            "exact": {"case_causes": ["房屋租赁合同纠纷"], "category_l1": "房地产纠纷", "category_l2": "租赁合同", "keywords": ["押金", "返还"]},
        }
        self.assertGreater(label_match_score(labels, payloads["exact"]), label_match_score(labels, payloads["semantic"]))
        self.assertEqual(label_weighted_rerank(["semantic", "exact"], payloads, labels, label_weight=0.8)[0], "exact")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from lawagent_ingestion.cases.pipeline import build_retrieval_text, content_hash, normalize_case, redact_text


def sample_case(case_id: str = "abc") -> dict:
    return {
        "Case": "张三与李四租赁合同纠纷案",
        "CaseCause": ["房屋租赁合同纠纷"],
        "CaseId": case_id,
        "CaseProc": "民事一审",
        "CaseRecord": "张三起诉李四。",
        "CaseType": "民事案件",
        "Category": [{"cat_1": "合同事务", "cat_2": "租赁合同"}],
        "JudgeAccusation": "张三请求李四返还押金。",
        "JudgeReason": "本院认为应当返还。",
        "JudgeResult": "李四返还押金。",
        "Keywords": ["押金"],
        "LegalBasis": [{"law": "《民法典》", "terms": "第七百零三条"}],
        "Parties": [{"NameText": "张三", "Prop": "原告", "LegalEntity": "Person"}, {"NameText": "李四", "Prop": "被告", "LegalEntity": "Person"}],
    }


class CaseIngestionTest(unittest.TestCase):
    def test_retrieval_text_excludes_answer_fields(self) -> None:
        raw = sample_case()
        _, point = normalize_case(raw, ["0.json#ctxs/1"])
        self.assertNotIn(raw["JudgeReason"], point.retrieval_text)
        self.assertNotIn(raw["JudgeResult"], point.retrieval_text)
        self.assertNotIn("民法典", point.retrieval_text)
        self.assertIn("返还押金", point.retrieval_text)

    def test_party_names_are_redacted_from_retrieval(self) -> None:
        _, point = normalize_case(sample_case(), ["0.json#ctxs/1"])
        self.assertNotIn("张三", point.retrieval_text)
        self.assertNotIn("李四", point.retrieval_text)
        self.assertIn("[原告]", point.retrieval_text)

    def test_case_id_is_preserved_and_version_is_content_based(self) -> None:
        first, first_point = normalize_case(sample_case("original-id"), ["0.json#ctxs/1"])
        changed = sample_case("original-id")
        changed["JudgeAccusation"] += "新增事实。"
        second, second_point = normalize_case(changed, ["1.json#ctxs/2"])
        self.assertEqual(first.case_id, "original-id")
        self.assertNotEqual(first.case_version_id, second.case_version_id)
        self.assertNotEqual(first_point.point_id, second_point.point_id)

    def test_content_hash_ignores_dictionary_order(self) -> None:
        self.assertEqual(content_hash({"a": 1, "b": 2}), content_hash({"b": 2, "a": 1}))

    def test_sensitive_patterns_are_redacted(self) -> None:
        value = redact_text("电话13812345678，身份证110101199001011234", [])
        self.assertNotIn("13812345678", value)
        self.assertNotIn("110101199001011234", value)

    def test_null_legal_basis_fields_are_preserved_as_empty(self) -> None:
        raw = sample_case()
        raw["LegalBasis"] = [{"law": None, "terms": None}]
        document, _ = normalize_case(raw, ["0.json#ctxs/1"])
        self.assertEqual(document.legal_basis[0].law, "")
        self.assertEqual(document.legal_basis[0].terms, "")


if __name__ == "__main__":
    unittest.main()

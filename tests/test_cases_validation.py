from __future__ import annotations

import unittest

from lawagent_ingestion.cases.validation import expected_retrieval_text


class CaseValidationTest(unittest.TestCase):
    def test_expected_retrieval_text_uses_only_allowlisted_fields(self) -> None:
        point = {
            "case_type": "民事案件", "procedure": "民事一审", "case_causes": ["租赁合同纠纷"],
            "category_l1": "合同事务", "category_l2": "租赁合同", "case_record": "案件经过",
            "claims_and_facts": "返还押金", "keywords": ["押金"], "judge_reason": "不得泄漏的理由",
            "judge_result": "不得泄漏的结果", "legal_basis": [{"law": "不得泄漏的法律"}],
        }
        text = expected_retrieval_text(point)
        self.assertIn("返还押金", text)
        self.assertNotIn("不得泄漏", text)

    def test_expected_retrieval_text_handles_empty_case(self) -> None:
        self.assertEqual(expected_retrieval_text({}), "案例事实信息缺失")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from scenario_pack import RentalDepositScenarioPack


class RentalDepositScenarioPackE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = RentalDepositScenarioPack()

    def test_statement_drives_pack_rules(self) -> None:
        facts = self.pack.extract_facts(
            "住宅已经退租并交了钥匙，押金3000元有转账记录。合同约定提前退租有违约金，"
            "房东说房屋损坏要扣款，争议日期是2026-08-20。",
            {},
        )
        self.assertEqual(facts["deposit_amount"], "3000元")
        self.assertFalse(self.pack.is_out_of_scope(facts))
        applicable = {
            item.item_key for item in self.pack.claim_items()
            if self.pack.is_claim_item_applicable(item.item_key, facts) == "applicable"
        }
        self.assertEqual(applicable, {
            "refundable_deposit_base", "deductions", "liquidated_damages",
            "overdue_interest", "disputed_deductions",
        })

    def test_excluded_scenarios_are_classified_without_error(self) -> None:
        for text in ("这是商铺押金纠纷", "我是转租后产生的押金纠纷", "这是群租住房"):
            with self.subTest(text=text):
                self.assertTrue(self.pack.is_out_of_scope(self.pack.extract_facts(text, {})))

    def test_extraction_does_not_mutate_or_replace_existing_facts(self) -> None:
        existing = {"tenancy_ended": "no", "deposit_amount": "2000元"}
        extracted = self.pack.extract_facts("已经退租，押金3000元", existing)
        self.assertEqual(existing, {"tenancy_ended": "no", "deposit_amount": "2000元"})
        self.assertNotIn("tenancy_ended", extracted)
        self.assertNotIn("deposit_amount", extracted)

    def test_action_template_is_conditionally_selected(self) -> None:
        standard = self.pack.action_templates({"contract_terms": "mentioned"})
        missing = self.pack.action_templates({"contract_terms": "no_written_contract"})
        self.assertNotEqual(standard.condition_key, missing.condition_key)
        self.assertTrue(missing.materials)


if __name__ == "__main__":
    unittest.main()

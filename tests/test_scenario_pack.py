from __future__ import annotations

import unittest

from pydantic import ValidationError

from scenario_pack import FactKeySpec, RentalDepositScenarioPack, ScenarioPack


class ScenarioPackContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = RentalDepositScenarioPack()

    def test_implements_protocol_and_declares_intake_contract(self) -> None:
        self.assertIsInstance(self.pack, ScenarioPack)
        keys = {spec.key for spec in self.pack.required_fact_keys("intake") if spec.required}
        self.assertEqual(keys, {
            "tenancy_ended", "deposit_amount", "counterparty_position",
            "contract_terms", "evidence", "event_date", "scope_status",
        })

    def test_specs_are_strict_and_immutable(self) -> None:
        spec = self.pack.required_fact_keys("intake")[0]
        with self.assertRaises(ValidationError):
            spec.key = "changed"
        with self.assertRaises(ValidationError):
            FactKeySpec(key="x", layer="invalid", required=True, description="x")  # type: ignore[arg-type]

    def test_claim_items_are_exactly_the_approved_five_with_catchall(self) -> None:
        items = self.pack.claim_items()
        self.assertEqual(
            [item.display_name for item in items],
            ["应退押金基数", "扣除项", "违约金", "逾期利息/资金占用赔偿", "争议扣除项"],
        )
        self.assertTrue(all(item.legal_basis_hint for item in items))
        self.assertTrue(all(item.applicability_signal for item in items))
        self.assertTrue(any(item.relief_kind == "disputed_catchall" for item in items))

    def test_party_labels_and_three_state_claim_applicability(self) -> None:
        labels = self.pack.party_labels({})
        self.assertEqual((labels.self_label, labels.counterparty_label), ("承租人", "房东"))
        self.assertEqual(
            self.pack.is_claim_item_applicable("refundable_deposit_base", {}),
            "uncertain",
        )
        with self.assertRaisesRegex(ValueError, "unknown claim item"):
            self.pack.is_claim_item_applicable("invented", {})


if __name__ == "__main__":
    unittest.main()

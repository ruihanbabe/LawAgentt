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
            "tenancy_ended", "deposit_amount", "landlord_reason",
            "contract_terms", "evidence", "event_date",
        })

    def test_specs_are_strict_and_immutable(self) -> None:
        spec = self.pack.required_fact_keys("intake")[0]
        with self.assertRaises(ValidationError):
            spec.key = "changed"
        with self.assertRaises(ValidationError):
            FactKeySpec(key="x", layer="invalid", required=True, description="x")  # type: ignore[arg-type]

    def test_amount_items_are_exactly_the_approved_five(self) -> None:
        items = self.pack.amount_calculation_items()
        self.assertEqual(
            [item.display_name for item in items],
            ["应退押金基数", "扣除项", "违约金", "逾期利息/资金占用赔偿", "争议扣除项"],
        )
        self.assertTrue(all(item.legal_basis_hint for item in items))

    def test_unknown_amount_item_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown amount item"):
            self.pack.is_amount_item_applicable("invented", {})


if __name__ == "__main__":
    unittest.main()

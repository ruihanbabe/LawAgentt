from __future__ import annotations

import unittest

from scenario_pack import PlaceholderScenarioPack, ScenarioPack


class PlaceholderScenarioPackTests(unittest.TestCase):
    def test_implements_same_minimal_protocol(self) -> None:
        pack = PlaceholderScenarioPack()
        self.assertIsInstance(pack, ScenarioPack)
        self.assertEqual([item.key for item in pack.required_fact_keys("intake")], ["topic"])
        self.assertEqual(pack.required_fact_keys("analysis"), [])
        self.assertEqual(pack.claim_items(), [])
        self.assertEqual(pack.party_labels({}).counterparty_label, "对方")

    def test_extracts_only_topic_without_mutating_existing_facts(self) -> None:
        pack = PlaceholderScenarioPack()
        existing = {"known": "value"}
        self.assertEqual(pack.extract_facts("处理示例事项", existing), {"topic": "处理示例事项"})
        self.assertEqual(existing, {"known": "value"})
        self.assertEqual(pack.extract_facts("新事项", {"topic": "已有事项"}), {})


if __name__ == "__main__":
    unittest.main()

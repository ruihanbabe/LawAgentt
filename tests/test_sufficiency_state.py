from __future__ import annotations

import unittest

from pydantic import ValidationError

from conversation.harness import build_default_harness
from intake.blackboard import SufficiencyConfig, SufficiencyDecision, SufficiencyState


class SufficiencyStateTests(unittest.TestCase):
    def test_default_limit_is_four_and_cross_field_limit_is_enforced(self) -> None:
        self.assertEqual(SufficiencyConfig().max_clarification_rounds, 4)
        state = SufficiencyState(clarification_round=4, max_clarification_rounds=4)
        self.assertEqual(state.clarification_round, 4)
        with self.assertRaises(ValidationError):
            SufficiencyState(clarification_round=5, max_clarification_rounds=4)

    def test_injected_limit_controls_understanding_without_class_literal(self) -> None:
        harness = build_default_harness(
            sufficiency_config=SufficiencyConfig(max_clarification_rounds=1)
        )
        first = harness.handle("住宅押金纠纷", session_id="configured-limit")
        second = harness.handle("没有更多信息", session_id="configured-limit")

        self.assertEqual(first.board.blackboard.sufficiency.clarification_round, 1)
        self.assertEqual(second.board.blackboard.sufficiency.clarification_round, 1)
        self.assertEqual(
            second.board.blackboard.sufficiency.decision,
            SufficiencyDecision.DELIVER_LIMITED_RESPONSE,
        )


if __name__ == "__main__":
    unittest.main()

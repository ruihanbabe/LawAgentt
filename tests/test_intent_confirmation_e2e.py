from __future__ import annotations

import unittest

from conversation.harness import build_default_harness
from intake.blackboard import ConsultationIntent, SufficiencyDecision


COMPLETE_FACTS = (
    "境内住宅租赁争议发生于2024-06-01，我已退租交还钥匙，押金3000元，"
    "房东说房屋损坏，合同有押金条款，我有转账和聊天记录。"
)


class IntentConfirmationE2ETests(unittest.TestCase):
    def test_fixed_option_confirmation_is_separate_from_clarification_budget(self) -> None:
        harness = build_default_harness()

        pending = harness.handle(COMPLETE_FACTS, session_id="intent-confirmation")
        free_text = harness.handle("我主要想维护自己的权益", session_id="intent-confirmation")
        confirmed = harness.handle("B", session_id="intent-confirmation")

        self.assertEqual(pending.board.blackboard.sufficiency.decision, SufficiencyDecision.CONFIRM_INTENT)
        self.assertIn("A. 我想了解是否有法律依据", pending.response)
        self.assertEqual(pending.board.blackboard.sufficiency.clarification_round, 0)
        self.assertEqual(free_text.board.blackboard.sufficiency.decision, SufficiencyDecision.CONFIRM_INTENT)
        self.assertIsNone(free_text.board.blackboard.sufficiency.confirmed_intent)
        self.assertEqual(free_text.board.blackboard.sufficiency.clarification_round, 0)
        self.assertEqual(confirmed.board.blackboard.sufficiency.decision, SufficiencyDecision.START_RETRIEVAL)
        self.assertEqual(confirmed.board.blackboard.sufficiency.confirmed_intent, ConsultationIntent.NEGOTIATION)
        self.assertEqual(confirmed.board.blackboard.sufficiency.clarification_round, 0)
        self.assertIn("retrieve_context", [task.task_type for task in confirmed.board.tasks])


if __name__ == "__main__":
    unittest.main()

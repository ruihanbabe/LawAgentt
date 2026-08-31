from __future__ import annotations

import unittest

from lawagent_evaluation.closed_pool import _ranking


class ClosedPoolEvaluationTest(unittest.TestCase):
    def test_ranking_sorts_scores_descending_with_stable_ties(self) -> None:
        self.assertEqual(_ranking(["a", "b", "c"], [0.1, 0.3, 0.3]), ["b", "c", "a"])


if __name__ == "__main__":
    unittest.main()

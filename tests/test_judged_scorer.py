from __future__ import annotations

import unittest

from qtpp.judged_scorer import HARD_FLOOR, JudgedPairScorer, Judgments


class ConstantScorer:
    def score(self, first_id: str, second_id: str) -> float:
        return 0.2


class JudgedPairScorerTests(unittest.TestCase):
    def test_overlay_is_order_independent(self) -> None:
        judgments = Judgments(frozenset({("a", "b")}), frozenset({("c", "d")}))
        scorer = JudgedPairScorer(ConstantScorer(), judgments, HARD_FLOOR)
        self.assertEqual(scorer.score("b", "a"), HARD_FLOOR)
        self.assertEqual(scorer.score("d", "c"), 0.0)
        self.assertEqual(scorer.score("a", "c"), 0.2)

    def test_flagged_together_counts_shared_packets(self) -> None:
        judgments = Judgments(frozenset({("a", "b"), ("a", "c")}))
        self.assertEqual(judgments.flagged_together([{"a", "b"}, {"c"}]), 1)


if __name__ == "__main__":
    unittest.main()

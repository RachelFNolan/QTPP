import unittest

from packetizer.scoring import (
    CachedScorer,
    PacketLayout,
    SoftWeights,
    score_layouts,
    score_packet,
)


class _Table:
    def __init__(self, values):
        self.values = values
        self.calls = 0

    def score(self, first, second):
        self.calls += 1
        return self.values.get(frozenset((first, second)), 0.0)


CATEGORIES = {"t1": "History", "t2": "History", "t3": "Science", "b1": "History", "b2": "Science"}


class ScoringTests(unittest.TestCase):
    def test_penalizes_adjacent_same_category_tossups(self) -> None:
        scorer = _Table({})
        adjacent = PacketLayout(("t1", "t2", "t3"), ())
        separated = PacketLayout(("t1", "t3", "t2"), ())
        self.assertEqual(score_packet(adjacent, CATEGORIES, scorer).adjacent_category, 1.0)
        self.assertEqual(score_packet(separated, CATEGORIES, scorer).adjacent_category, 0.0)

    def test_same_packet_and_nearby_terms_decay_with_distance(self) -> None:
        scorer = _Table({frozenset(("t1", "t3")): 0.5})
        weights = SoftWeights(adjacent_category=0, same_packet=1, nearby=2, window=2)
        close = score_packet(PacketLayout(("t1", "t3", "t2"), ()), CATEGORIES, scorer, weights)
        far = score_packet(PacketLayout(("t1", "t2", "t3"), ()), CATEGORIES, scorer, weights)
        self.assertAlmostEqual(close.same_packet, 0.5)
        self.assertAlmostEqual(close.nearby, 2 * 0.5)
        self.assertAlmostEqual(far.nearby, 2 * 0.5 / 2)

    def test_layout_totals_sum_terms_and_cache_is_symmetric(self) -> None:
        table = _Table({frozenset(("t1", "b1")): 0.4})
        scorer = CachedScorer(table)
        layouts = [PacketLayout(("t1",), ("b1",)), PacketLayout(("t3",), ("b2",))]
        score = score_layouts(layouts, CATEGORIES, scorer, SoftWeights(1, 1, 1))
        self.assertAlmostEqual(score.same_packet, 0.4)
        self.assertAlmostEqual(score.total, 0.4)
        scorer.score("b1", "t1")
        self.assertEqual(table.calls, 2)

    def test_rejects_invalid_weights(self) -> None:
        with self.assertRaises(ValueError):
            SoftWeights(window=0)
        with self.assertRaises(ValueError):
            SoftWeights(nearby=-1)


if __name__ == "__main__":
    unittest.main()

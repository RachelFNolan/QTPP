import json
import tempfile
import unittest
from pathlib import Path

from qtpp import Bonus, Difficulty, QuestionSet, load_question_set


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_SET = PROJECT_ROOT / "Test Questions" / "2025 ACF Winter"


@unittest.skipUnless(SAMPLE_SET.is_dir(), "sample packet JSON folder is not checked in")
class LoadQuestionSetTests(unittest.TestCase):
    def test_loads_supplied_question_set(self) -> None:
        question_set = load_question_set(SAMPLE_SET)

        self.assertIsInstance(question_set, QuestionSet)
        self.assertEqual(question_set.metadata.name, "2025 ACF Winter")
        self.assertEqual(len(question_set.packets), 17)
        self.assertEqual(len(question_set.tossups), 330)
        self.assertEqual(len(question_set.bonuses), 331)
        self.assertEqual([packet.number for packet in question_set.packets], sorted(
            packet.number for packet in question_set.packets
        ))
        self.assertEqual(sum(len(packet.tossups) for packet in question_set.packets), len(question_set.tossups))
        self.assertEqual(sum(len(packet.bonuses) for packet in question_set.packets), len(question_set.bonuses))

    def test_maps_bonus_parts_without_losing_source_text(self) -> None:
        packet_file = SAMPLE_SET / "A_Toronto-A_City-St-Georges_Sheffield-A_McMaster-A_Chicago-B.json"
        question_set = load_question_set(packet_file.parent)
        packet = question_set.packets[0]
        bonus_id = packet.bonuses[0].question_id
        bonus = next(question for question in question_set.bonuses if question.metadata.id == bonus_id)

        self.assertIsInstance(bonus, Bonus)
        self.assertEqual(len(bonus.parts), 3)
        self.assertEqual([part.number for part in bonus.parts], [1, 2, 3])
        self.assertEqual([part.value for part in bonus.parts], [10, 10, 10])
        self.assertIn("<i>", bonus.parts[1].question)
        self.assertNotIn("<i>", bonus.parts[1].question_sanitized)

    def test_question_pool_can_exist_before_packetization(self) -> None:
        imported_set = load_question_set(SAMPLE_SET)
        question_pool = QuestionSet(
            metadata=imported_set.metadata,
            tossups=imported_set.tossups,
            bonuses=imported_set.bonuses,
        )

        self.assertEqual(len(question_pool.tossups), 330)
        self.assertEqual(len(question_pool.bonuses), 331)
        self.assertEqual(question_pool.packets, ())

    def test_reads_set_difficulty_with_named_sublevel(self) -> None:
        source = json.loads(
            (SAMPLE_SET / "A_Toronto-A_City-St-Georges_Sheffield-A_McMaster-A_Chicago-B.json").read_text()
        )
        for question in source["tossups"] + source["bonuses"]:
            question["set"]["difficulty"] = {"level": "College", "sublevel": "Medium"}
        source["tossups"][0]["difficulty"] = {"level": "College", "sublevel": 8}

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "packet.json"
            path.write_text(json.dumps(source))
            question_set = load_question_set(path.parent)

        self.assertEqual(question_set.metadata.difficulty, Difficulty(level="College", sublevel="Medium"))
        self.assertEqual(question_set.tossups[0].metadata.difficulty, Difficulty(level="College", sublevel=8))
        self.assertIsNone(question_set.tossups[1].metadata.difficulty)

    def test_rejects_mismatched_bonus_part_arrays(self) -> None:
        source = json.loads((SAMPLE_SET / "A_Toronto-A_City-St-Georges_Sheffield-A_McMaster-A_Chicago-B.json").read_text())
        source["bonuses"][0]["answers"].pop()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "packet.json"
            path.write_text(json.dumps(source))

            with self.assertRaisesRegex(ValueError, "equal nonzero lengths"):
                load_question_set(path.parent)


if __name__ == "__main__":
    unittest.main()

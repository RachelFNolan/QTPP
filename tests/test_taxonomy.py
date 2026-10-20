import json
import tempfile
import unittest
from pathlib import Path

from qtpp import (
    QuestionMetadata,
    QuestionSet,
    QuestionSetMetadata,
    Topic,
    Tossup,
    build_similarity,
    detect_eras,
    detect_regions,
    load_taxonomy,
    load_time_place_tags,
    question_families,
)
from qtpp.family_suggest import approve_suggestions, save_suggestions, suggest_with_taxonomy
from qtpp.taxonomy import taxonomy_from_dict
from qtpp.time_place import detect_era, detect_region, save_time_place_tags

TAXONOMY = taxonomy_from_dict(
    {
        "categories": {
            "Fine Arts": {
                "catch_all": ["Other"],
                "labels": {
                    "Opera": {"description": "opera aria libretto soprano", "subcategories": ["Auditory Fine Arts"]},
                    "Painting": {"description": "painting painter canvas oils", "subcategories": ["Visual Fine Arts"]},
                    "Mathematics": {"description": "theorem proof algebra", "aliases": ["Math"]},
                },
            }
        }
    }
)


def tossup(question_id, text, subcategory, alternate=None, category="Fine Arts"):
    return Tossup(QuestionMetadata(question_id, Topic(category, subcategory, alternate)), text, "ans")


def pool(*questions) -> QuestionSet:
    return QuestionSet(QuestionSetMetadata("t", "T", 2025, None), tuple(questions), ())


class TaxonomyTests(unittest.TestCase):
    def test_default_taxonomy_loads_with_user_labels_and_aliases(self) -> None:
        taxonomy = load_taxonomy()
        names = {label.name for label in taxonomy.category("Literature").labels}
        self.assertEqual(names, {"Drama", "Poetry", "Long Fiction", "Short Fiction"})
        aliases = taxonomy.alias_map()
        self.assertEqual(aliases["math"], "Mathematics")
        self.assertEqual(aliases["astronomy"], "Astrophysics")
        self.assertIn("other", taxonomy.catch_alls())

    def test_invalid_taxonomy_rejected(self) -> None:
        for bad in ({}, {"categories": {"X": {}}}, {"categories": {"X": {"labels": {"A": {"description": 3}}}}}):
            with self.assertRaises(ValueError):
                taxonomy_from_dict(bad)

    def test_aliases_merge_families(self) -> None:
        questions = [
            tossup("a", "q", "Other Science", "Math", "Science"),
            tossup("b", "q", "Other Science", "Mathematics", "Science"),
            tossup("c", "q", "Other Science", "Other", "Science"),
        ]
        families = question_families(questions, aliases=TAXONOMY.alias_map())
        self.assertEqual(families["a"], families["b"])
        self.assertEqual(families["c"], frozenset())


class SuggestTaxonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = pool(
            tossup("op", "soprano sings an aria from the opera libretto", "Auditory Fine Arts"),
            tossup("opv", "soprano sings an aria from the opera libretto", "Visual Fine Arts"),
            tossup("done", "painting of a painter", "Visual Fine Arts", "Painting"),
            tossup("bio", "soprano aria opera", "Biology", category="Science"),
        )

    def test_scoped_by_category_and_subcategory_and_skips_tagged(self) -> None:
        result = {s.question_id: s for s in suggest_with_taxonomy(self.pool, TAXONOMY)}
        self.assertEqual(set(result), {"op", "opv"})
        self.assertEqual(result["op"].label, "Opera")
        self.assertNotEqual(result["opv"].best_guess, "Opera")

    def test_auto_status_uses_margin(self) -> None:
        loose = {s.question_id: s for s in suggest_with_taxonomy(self.pool, TAXONOMY, auto_margin=0.0)}
        strict = {s.question_id: s for s in suggest_with_taxonomy(self.pool, TAXONOMY, auto_margin=5.0)}
        self.assertEqual(loose["op"].status, "auto")
        self.assertEqual(strict["op"].status, "review")

    def test_example_check_sends_disagreements_to_review(self) -> None:
        examples = [
            tossup(f"e{i}", "xylophone marimba mallet", "Auditory Fine Arts", "Opera") for i in range(5)
        ] + [
            tossup(f"m{i}", "soprano sings an aria from the opera libretto", "Auditory Fine Arts", "Math")
            for i in range(5)
        ]
        combined = pool(*self.pool.tossups, *examples)
        agreed = {s.question_id: s for s in suggest_with_taxonomy(combined, TAXONOMY, use_examples=False)}
        checked = {s.question_id: s for s in suggest_with_taxonomy(combined, TAXONOMY)}
        self.assertEqual(agreed["op"].label, "Opera")
        self.assertIsNone(checked["op"].label)
        self.assertEqual(checked["op"].status, "unsure")

    def test_approve_auto_only(self) -> None:
        suggestions = suggest_with_taxonomy(self.pool, TAXONOMY, auto_margin=0.0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.json"
            save_suggestions(suggestions, path)
            self.assertEqual(approve_suggestions(path)["op"], ["Opera"])
            data = json.loads(path.read_text())
            data["suggestions"][0]["status"] = "review"
            path.write_text(json.dumps(data))
            self.assertNotIn(data["suggestions"][0]["question_id"], approve_suggestions(path, auto_only=True))


class TimePlaceTests(unittest.TestCase):
    def test_era_detection(self) -> None:
        self.assertEqual(detect_era("In 1848 and 1851 revolutions"), "Long 19th century (1789-1914)")
        self.assertEqual(detect_era("a 17th-century manuscript"), "Early modern (1500-1789)")
        self.assertEqual(detect_era("in 44 BCE he fell"), "Ancient (before 500)")
        self.assertIsNone(detect_era("ten points for this thing"))

    def test_region_detection_needs_a_clear_winner(self) -> None:
        self.assertEqual(detect_region("Tokyo and Kyoto in Japan"), "East Asia")
        self.assertIsNone(detect_region("France and Japan"))
        self.assertIsNone(detect_region("nothing here"))

    def test_penalty_is_opt_in_and_category_scoped(self) -> None:
        history = [
            tossup("h1", "Napoleon in 1805 France", "European History", category="History"),
            tossup("h2", "Napoleon in 1812 France", "European History", category="History"),
            tossup("s1", "Napoleon in 1805 France", "Biology", category="Science"),
        ]
        questions = pool(*history)
        eras, regions = detect_eras(questions), detect_regions(questions)
        self.assertEqual(eras["h1"], eras["h2"])
        plain = build_similarity(questions)
        tagged = build_similarity(questions, eras=eras, regions=regions, era_penalty=0.2, region_penalty=0.1)
        self.assertAlmostEqual(tagged.score("h1", "h2"), min(1.0, plain.score("h1", "h2") + 0.3))
        untouched = build_similarity(questions, eras=eras, regions=regions)
        self.assertAlmostEqual(untouched.score("h1", "h2"), plain.score("h1", "h2"))
        scoped = build_similarity(questions, eras={"h1": "x", "s1": "x"}, era_penalty=0.5)
        self.assertAlmostEqual(scoped.score("h1", "s1"), plain.score("h1", "s1"))

    def test_tags_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tags.json"
            save_time_place_tags({"a": "E"}, {"a": "R"}, path)
            self.assertEqual(load_time_place_tags(path), ({"a": "E"}, {"a": "R"}))
            path.write_text('{"eras": {"a": 1}}')
            with self.assertRaises(ValueError):
                load_time_place_tags(path)


if __name__ == "__main__":
    unittest.main()


class SuggestedFamilyScoringTests(unittest.TestCase):
    def test_suggested_tags_use_reduced_penalty_and_confirmed_wins(self) -> None:
        questions = pool(
            tossup("a", "alpha text", "Other Science", None, "Science"),
            tossup("b", "beta text", "Other Science", None, "Science"),
            tossup("c", "gamma text", "Other Science", "Mathematics", "Science"),
            tossup("d", "delta text", "Other Science", "Math", "Science"),
        )
        plain = build_similarity(questions)
        scorer = build_similarity(
            questions, family_penalty=0.4, suggested_families={"a": ["Math"], "b": ["mathematics"]}
        )
        self.assertAlmostEqual(scorer.score("a", "b"), plain.score("a", "b") + 0.2)
        self.assertAlmostEqual(scorer.score("c", "d"), plain.score("c", "d") + 0.4)
        self.assertAlmostEqual(scorer.score("a", "c"), plain.score("a", "c") + 0.2)
        explicit = build_similarity(
            questions, family_penalty=0.4, suggested_families={"a": ["Math"], "b": ["Math"]}, suggested_penalty=0.1
        )
        self.assertAlmostEqual(explicit.score("a", "b"), plain.score("a", "b") + 0.1)
        self.assertAlmostEqual(build_similarity(questions, suggested_families={"a": ["Math"], "b": ["Math"]}).score("a", "b"), plain.score("a", "b"))

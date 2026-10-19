import json
import tempfile
import unittest
from pathlib import Path

from packetizer import (
    AllowedCountPatterns,
    BuildTemplate,
    CategoryCountRule,
    CountSelector,
    load_template,
    save_template,
    template_from_dict,
    template_to_dict,
)

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
WINTER_FINAL = TEMPLATES / "acf-winter-final.json"
FALL_FINAL = TEMPLATES / "acf-fall-final.json"


class TemplateJsonTests(unittest.TestCase):
    def test_checked_in_templates_round_trip_through_file(self) -> None:
        blank = BuildTemplate("Blank", 10, 10, quotas=(), allowed_patterns=())
        templates = [load_template(path) for path in sorted(TEMPLATES.glob("*.json"))]
        self.assertGreaterEqual(len(templates), 3)
        for template in (*templates, blank):
            with self.subTest(template=template.name), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "template.json"
                save_template(template, path)
                self.assertEqual(load_template(path), template)

    def test_json_serializes_compact_category_count_rule(self) -> None:
        data = template_to_dict(load_template(WINTER_FINAL))
        other = data["allowed_patterns"][0]
        self.assertEqual(
            other["categories"],
            ["Geography", "Current Events", "Pop Culture", "Other Academic"],
        )
        self.assertEqual(other["counts"], {"tossup": 1, "bonus": 1})
        self.assertTrue(other["distinct_categories"])
        json.dumps(data)

    def test_json_serializes_grouped_category_count_rule(self) -> None:
        data = template_to_dict(load_template(FALL_FINAL))
        rule = data["allowed_patterns"][0]
        self.assertEqual(rule["counts"], {"tossup": 3, "bonus": 3})
        self.assertEqual(len(rule["groups"]), 2)
        self.assertEqual(rule["groups"][0]["total"], 3)
        self.assertEqual(rule["groups"][0]["minimum_per_category"], 1)
        self.assertEqual(rule["groups"][0]["maximum_per_category_per_type"], 1)
        self.assertTrue(rule["groups"][1]["distinct_categories"])

    def test_reads_legacy_explicit_pattern_rules(self) -> None:
        data = {
            "schema_version": 1,
            "name": "Explicit patterns",
            "tossup_capacity": 1,
            "bonus_capacity": 1,
            "quotas": [],
            "allowed_patterns": [{
                "name": "Pair",
                "selectors": [
                    {"question_type": "tossup", "category": "History", "subcategory": "World"},
                    {"question_type": "bonus", "category": "Science", "subcategory": "Biology"},
                ],
                "patterns": [{"tossup:History:World": 1, "bonus:Science:Biology": 1}],
            }],
        }
        template = template_from_dict(data)
        self.assertEqual(
            template.allowed_patterns[0],
            AllowedCountPatterns(
                "Pair",
                (
                    CountSelector("tossup", "History", "World"),
                    CountSelector("bonus", "Science", "Biology"),
                ),
                ((1, 1),),
            ),
        )

    def test_rejects_invalid_templates(self) -> None:
        data = template_to_dict(load_template(WINTER_FINAL))
        with self.assertRaisesRegex(ValueError, "schema_version"):
            template_from_dict({**data, "schema_version": 99})
        missing = {key: value for key, value in data.items() if key != "name"}
        with self.assertRaisesRegex(ValueError, "missing required field 'name'"):
            template_from_dict(missing)
        data["allowed_patterns"] = [{
            "name": "Invalid",
            "selectors": [
                {"question_type": "tossup", "category": "History", "subcategory": "World"}
            ],
            "patterns": [{"tossup:Nope:Nope": 1}],
        }]
        with self.assertRaisesRegex(ValueError, "unknown selector"):
            template_from_dict(data)

    def test_load_reports_invalid_json_with_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text("{")
            with self.assertRaisesRegex(ValueError, "bad.json: invalid JSON"):
                load_template(path)


if __name__ == "__main__":
    unittest.main()

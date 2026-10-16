import json
import tempfile
import unittest
from pathlib import Path

from packetizer import (
    BuildTemplate,
    load_template,
    save_template,
    template_from_dict,
    template_to_dict,
)

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
WINTER_FINAL = TEMPLATES / "acf-winter-final.json"


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

    def test_json_is_readable_with_labeled_nonzero_pattern_counts(self) -> None:
        data = template_to_dict(load_template(WINTER_FINAL))
        other = data["allowed_patterns"][0]
        self.assertEqual(len(other["patterns"]), 12)
        first = other["patterns"][0]
        self.assertEqual(sum(first.values()), 2)
        self.assertTrue(all(label.count(":") == 2 for label in first))
        json.dumps(data)

    def test_rejects_invalid_templates(self) -> None:
        data = template_to_dict(load_template(WINTER_FINAL))
        with self.assertRaisesRegex(ValueError, "schema_version"):
            template_from_dict({**data, "schema_version": 99})
        missing = {key: value for key, value in data.items() if key != "name"}
        with self.assertRaisesRegex(ValueError, "missing required field 'name'"):
            template_from_dict(missing)
        data["allowed_patterns"][0]["patterns"][0] = {"tossup:Nope:Nope": 1}
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

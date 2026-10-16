import json
import tempfile
import unittest
from pathlib import Path

from packetizer import (
    acf_winter_final_template,
    acf_winter_submitted_template,
    blank_build_template,
    load_template,
    save_template,
    template_from_dict,
    template_to_dict,
)


class TemplateJsonTests(unittest.TestCase):
    def test_presets_round_trip_through_file(self) -> None:
        for template in (
            acf_winter_final_template(),
            acf_winter_submitted_template(),
            blank_build_template(10, 10),
        ):
            with self.subTest(template=template.name), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "template.json"
                save_template(template, path)
                self.assertEqual(load_template(path), template)

    def test_json_is_readable_with_labeled_nonzero_pattern_counts(self) -> None:
        data = template_to_dict(acf_winter_final_template())
        other = data["allowed_patterns"][0]
        self.assertEqual(len(other["patterns"]), 12)
        first = other["patterns"][0]
        self.assertEqual(sum(first.values()), 2)
        self.assertTrue(all(label.count(":") == 2 for label in first))
        json.dumps(data)

    def test_rejects_invalid_templates(self) -> None:
        data = template_to_dict(acf_winter_final_template())
        with self.assertRaisesRegex(ValueError, "schema_version"):
            template_from_dict({**data, "schema_version": 99})
        missing = {key: value for key, value in data.items() if key != "name"}
        with self.assertRaisesRegex(ValueError, "missing required field 'name'"):
            template_from_dict(missing)
        data["allowed_patterns"][0]["patterns"][0] = {"tossup:Nope:Nope": 1}
        with self.assertRaisesRegex(ValueError, "unknown selector"):
            template_from_dict(data)

    def test_checked_in_preset_files_match_code(self) -> None:
        root = Path(__file__).resolve().parents[1] / "templates"
        self.assertEqual(load_template(root / "acf-winter-final.json"), acf_winter_final_template())
        self.assertEqual(
            load_template(root / "acf-winter-submitted.json"), acf_winter_submitted_template()
        )

    def test_load_reports_invalid_json_with_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text("{")
            with self.assertRaisesRegex(ValueError, "bad.json: invalid JSON"):
                load_template(path)


if __name__ == "__main__":
    unittest.main()

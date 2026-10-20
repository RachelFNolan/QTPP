import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from qtpp import (
    FieldSelection,
    InfeasibleError,
    Run,
    build_packet_document,
    build_question_set,
    build_similarity,
    export_packets,
    generate_packets,
    load_authors,
    load_question_pool_csv,
    load_question_set,
    load_template,
    parse_markup,
    solve_baseline,
)
from qtpp.model import Packet, QuestionSetMetadata

ROOT = Path(__file__).resolve().parents[1]
WINTER = ROOT / "Test Questions" / "2025 ACF Winter"
FALL = ROOT / "Test Questions" / "2025 ACF Fall"


def _generate(directory: Path, template: str, packets: int = 3, seed: int = 1):
    pool = load_question_pool_csv(directory / "Question Pool.csv")
    spec = load_template(ROOT / "templates" / template).create_spec(packets)
    return pool, generate_packets(
        pool, spec, build_similarity(pool), seed=seed, iterations=300
    )


def _winter_result(pool, packets: int = 3):
    spec = load_template(ROOT / "templates" / "acf-winter-final.json").create_spec(packets)
    return solve_baseline(pool, spec, build_similarity(pool), iterations=50)


class GenerationExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pool, cls.generated = _generate(WINTER, "acf-winter-final.json")

    def test_materializes_numbered_packets_and_keeps_pool(self) -> None:
        question_set = self.generated.question_set
        self.assertEqual(len(question_set.packets), 3)
        self.assertEqual(question_set.tossups, self.pool.tossups)
        self.assertEqual(question_set.bonuses, self.pool.bonuses)
        for number, packet in enumerate(question_set.packets, start=1):
            self.assertEqual(packet.number, number)
            self.assertEqual(
                [p.number for p in packet.tossups], list(range(1, len(packet.tossups) + 1))
            )
        assigned = {
            p.question_id
            for packet in question_set.packets
            for p in (*packet.tossups, *packet.bonuses)
        }
        report = self.generated.report
        self.assertEqual(
            len(assigned) + len(report.leftover_ids),
            len(self.pool.tossups) + len(self.pool.bonuses),
        )
        self.assertFalse(assigned & set(report.leftover_ids))
        self.assertEqual(report.seed, 1)

    def test_same_seed_gives_identical_files(self) -> None:
        _, again = _generate(WINTER, "acf-winter-final.json")
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            export_packets(self.generated.question_set, first)
            export_packets(again.question_set, second)
            names = sorted(path.name for path in Path(first).iterdir())
            self.assertEqual(names, sorted(path.name for path in Path(second).iterdir()))
            for name in names:
                self.assertEqual(
                    (Path(first) / name).read_bytes(), (Path(second) / name).read_bytes()
                )

    def test_round_trips_through_importer(self) -> None:
        for directory, template in (
            (WINTER, "acf-winter-final.json"),
            (FALL, "acf-fall-final.json"),
        ):
            pool, generated = _generate(directory, template, packets=2)
            with self.subTest(directory=directory.name), tempfile.TemporaryDirectory() as out:
                export_packets(generated.question_set, out)
                loaded = load_question_set(out)
                original = generated.question_set
                self.assertEqual(loaded.metadata, original.metadata)
                self.assertEqual(loaded.packets, original.packets)
                used = {
                    p.question_id
                    for packet in original.packets
                    for p in (*packet.tossups, *packet.bonuses)
                }
                self.assertEqual(
                    {q.metadata.id for q in loaded.tossups + loaded.bonuses}, used
                )
                by_id = {q.metadata.id: q for q in pool.tossups + pool.bonuses}
                for question in loaded.tossups + loaded.bonuses:
                    self.assertEqual(question, by_id[question.metadata.id])

    def test_unknown_set_metadata_round_trips(self) -> None:
        metadata = QuestionSetMetadata(id="s", name="Set", year=2025, standard=None)
        question_set = dataclasses.replace(self.generated.question_set, metadata=metadata)
        with tempfile.TemporaryDirectory() as out:
            export_packets(question_set, out)
            self.assertIsNone(load_question_set(out).metadata.standard)

    def test_rejects_hard_rule_errors_and_infeasible_requests(self) -> None:
        bad = dataclasses.replace(_winter_result(self.pool, 2), hard_errors=("broken",))
        with self.assertRaises(InfeasibleError):
            build_question_set(self.pool, bad)
        spec = load_template(ROOT / "templates" / "acf-winter-final.json").create_spec(99)
        with self.assertRaises(InfeasibleError):
            generate_packets(self.pool, spec, build_similarity(self.pool))

    def test_empty_packet_exports_nothing(self) -> None:
        question_set = self.generated.question_set
        empty = Packet("p", "Empty", len(question_set.packets) + 1, (), ())
        broken = dataclasses.replace(question_set, packets=(*question_set.packets, empty))
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(ValueError, "empty"):
                export_packets(broken, out)
            self.assertEqual(list(Path(out).iterdir()), [])

    def test_packet_names_and_filenames(self) -> None:
        result = _winter_result(self.pool)
        question_set = build_question_set(self.pool, result, ["Round A/1", "B", "C"])
        with tempfile.TemporaryDirectory() as out:
            paths = export_packets(question_set, out)
            self.assertEqual(paths[0].name, "01_Round-A-1.json")
            record = json.loads(paths[0].read_text())["tossups"][0]
            self.assertEqual(record["packet"]["name"], "Round A/1")
        with self.assertRaises(ValueError):
            build_question_set(self.pool, result, ["only one"])


class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, generated = _generate(WINTER, "acf-winter-final.json", packets=2)
        cls.question_set = generated.question_set
        cls.packet = cls.question_set.packets[0]

    def test_parse_markup(self) -> None:
        runs = parse_markup("a <b><u>gill</u></b>s <i>x &amp; y</i> <span>z</span>")
        self.assertEqual(
            runs,
            (
                Run("a "),
                Run("gill", bold=True, underline=True),
                Run("s "),
                Run("x & y", italic=True),
                Run(" z"),
            ),
        )
        self.assertEqual(parse_markup("plain"), (Run("plain"),))
        self.assertEqual(parse_markup("<b>open"), (Run("open", bold=True),))
        self.assertEqual(parse_markup("x</b>y"), (Run("xy"),))
        self.assertEqual(parse_markup(""), ())

    def test_default_selection(self) -> None:
        document = build_packet_document(self.question_set, self.packet)
        self.assertEqual(document.front_matter.set_name, "2025 ACF Winter")
        self.assertEqual(document.front_matter.packet_number, 1)
        self.assertEqual(len(document.tossups), len(self.packet.tossups))
        self.assertTrue(all(t.answer is not None and not t.details for t in document.tossups))
        self.assertTrue(any(run.bold for t in document.tossups for run in t.answer))
        self.assertTrue(all(p.value is not None for b in document.bonuses for p in b.parts))

    def test_selection_adds_and_removes_fields(self) -> None:
        first_id = self.packet.tossups[0].question_id
        selection = FieldSelection(
            text_form="sanitized",
            include_answers=False,
            bonus_values=False,
            bonus_modifiers=False,
            category_subcategory=True,
            alternate_subcategory=True,
            source_question_id=True,
            author=True,
            front_set_name=False,
        )
        document = build_packet_document(
            self.question_set, self.packet, selection, {first_id: "Pat"}
        )
        tossup = document.tossups[0]
        self.assertIsNone(tossup.answer)
        self.assertEqual(tossup.details["source_question_id"], first_id)
        self.assertEqual(tossup.details["author"], "Pat")
        self.assertIn("category", tossup.details)
        self.assertNotIn("<", "".join(run.text for run in tossup.question))
        self.assertIsNone(document.front_matter.set_name)
        self.assertEqual(document.front_matter.authors, ("Pat",))
        part = document.bonuses[0].parts[0]
        self.assertIsNone(part.value)
        self.assertIsNone(part.modifier)

    def test_field_selection_round_trip_and_validation(self) -> None:
        selection = FieldSelection(text_form="sanitized", author=True)
        self.assertEqual(
            FieldSelection.from_dict(json.loads(json.dumps(selection.to_dict()))), selection
        )
        with self.assertRaisesRegex(ValueError, "unknown"):
            FieldSelection.from_dict({"nope": True})
        with self.assertRaises(ValueError):
            FieldSelection(text_form="html")
        with self.assertRaises(ValueError):
            FieldSelection.from_dict({"author": "yes"})

    def test_load_authors(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            path = Path(out) / "authors.json"
            path.write_text('{"authors": {"q1": "Pat"}}')
            self.assertEqual(load_authors(path), {"q1": "Pat"})
            path.write_text('{"authors": []}')
            with self.assertRaises(ValueError):
                load_authors(path)


if __name__ == "__main__":
    unittest.main()

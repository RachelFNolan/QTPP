from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from qtpp import cpsat_solver
from qtpp.json_import import load_question_set
from qtpp.model import (
    Bonus,
    BonusPart,
    QuestionMetadata,
    QuestionSet,
    QuestionSetMetadata,
    Topic,
    Tossup,
)
from qtpp.time_place import detect_century
from qtpp.web_app import WorkspaceServer
from qtpp.workspace import Workspace, WorkspaceError


def tiny_pool() -> QuestionSet:
    return QuestionSet(
        metadata=QuestionSetMetadata(
            id="demo-set", name="Demo Set", year=2025, standard=True
        ),
        tossups=(
            Tossup(
                QuestionMetadata("tu-1", Topic("History", "World History")),
                "A question about 20th century events in 1945.",
                "An answer",
            ),
        ),
        bonuses=(
            Bonus(
                QuestionMetadata("b-1", Topic("History", "American History")),
                "An undated lead-in",
                (BonusPart(1, "A bonus part", "An answer", 10, "standard"),),
            ),
        ),
    )


def tiny_template() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "Tiny test template",
        "tossup_capacity": 1,
        "bonus_capacity": 1,
        "quotas": [],
        "allowed_patterns": [],
        "leftover_bounds": [
            {"question_type": "tossup", "minimum": 0, "maximum": 0},
            {"question_type": "bonus", "minimum": 0, "maximum": 0},
        ],
    }


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace(templates_dir=tempfile.mkdtemp(), labels_path=Path(tempfile.mkdtemp()) / "labels.jsonl")
        self.workspace._set_pool(tiny_pool())

    def test_label_pair_appends_and_audit_reports_saved_label(self) -> None:
        self.workspace.generate(
            {
                "template": tiny_template(),
                "packet_count": 1,
                "solvers": ["baseline"],
                "similarities": ["balanced-tfidf"],
            }
        )
        result = self.workspace.label_pair(
            {"first_id": "tu-1", "second_id": "b-1", "label": "similar", "reviewer": "rn"}
        )
        self.assertEqual(result["summary"]["similar"], 1)
        self.workspace.label_pair({"first_id": "b-1", "second_id": "tu-1", "label": "different"})
        summary = self.workspace.label_pair(
            {"first_id": "tu-1", "second_id": "b-1", "label": "different"}
        )["summary"]
        self.assertEqual((summary["total"], summary["different"]), (1, 1))
        audit = self.workspace.audit("too much 20th century material")
        self.assertEqual(audit["likely_conflicts"][0]["saved_label"], "different")
        with self.assertRaises(WorkspaceError):
            self.workspace.label_pair({"first_id": "tu-1", "second_id": "tu-1", "label": "similar"})
        with self.assertRaises(WorkspaceError):
            self.workspace.label_pair({"first_id": "tu-1", "second_id": "b-1", "label": "maybe"})

    def _flag_top_conflicts(self, solver: str) -> None:
        self.workspace.import_demo()
        template = {**tiny_template(), "tossup_capacity": 3, "bonus_capacity": 3, "leftover_bounds": []}
        self.workspace.generate(
            {
                "template": template,
                "packet_count": 2,
                "solvers": [solver],
                "similarities": ["balanced-tfidf"],
                "baseline_samples": 3,
            }
        )
        for conflict in self.workspace.audit("")["likely_conflicts"][:3]:
            self.workspace.label_pair(
                {"first_id": conflict["first_id"], "second_id": conflict["second_id"], "label": "similar"}
            )

    def test_weight_sweep_reports_scale_and_sensitivity(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.weight_sweep({})
        self.workspace.import_demo()
        template = {**tiny_template(), "tossup_capacity": 3, "bonus_capacity": 3, "leftover_bounds": []}
        self.workspace.generate(
            {
                "template": template,
                "packet_count": 2,
                "solvers": ["baseline"],
                "similarities": ["balanced-tfidf"],
                "baseline_samples": 3,
            }
        )
        result = self.workspace.weight_sweep({"factors": [0, 2]})
        self.assertEqual(len(result["rows"]), 6)
        self.assertAlmostEqual(sum(item["share"] for item in result["scale"]), 1.0)
        self.assertTrue(all(0 <= row["membership_change"] <= 1 for row in result["rows"]))
        with self.assertRaises(WorkspaceError):
            self.workspace.weight_sweep({"factors": [-1]})
        with self.assertRaises(WorkspaceError):
            self.workspace.weight_sweep({"factors": "2"})

    def test_tune_weights_uses_a_fixed_yardstick_and_validates(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.tune_weights({})
        self.workspace.import_demo()
        template = {**tiny_template(), "tossup_capacity": 3, "bonus_capacity": 3, "leftover_bounds": []}
        self.workspace.generate(
            {
                "template": template,
                "packet_count": 2,
                "solvers": ["baseline"],
                "similarities": ["balanced-tfidf"],
                "baseline_samples": 3,
            }
        )
        result = self.workspace.tune_weights({"seeds": 1, "holdout": 2})
        self.assertEqual(result["current"]["weights"]["nearby"], 3.0)
        self.assertEqual(result["scorers"][0]["similarity_id"], "balanced-tfidf")
        self.assertGreaterEqual(result["evaluated_candidates"], 27)
        self.assertEqual(result["improved"], result["best"]["weights"] != result["current"]["weights"] and result["improved"])
        # Zeroing every weight must not look better: quality ignores the candidate weights.
        by_weights = {tuple(item["weights"][t] for t in ("adjacent_category", "same_packet", "nearby")): item["quality"] for item in result["top"]}
        self.assertTrue(all(quality <= result["best"]["quality"] + 1e-9 for quality in by_weights.values()))
        for bad in ({"seeds": 0}, {"seeds": 6}, {"holdout": 9}, {"time_limit": 0}, {"time_limit": "x"}):
            with self.assertRaises(WorkspaceError):
                self.workspace.tune_weights(bad)

    def test_tune_weights_reports_partial_results_on_time_limit(self) -> None:
        self.workspace.import_demo()
        template = {**tiny_template(), "tossup_capacity": 3, "bonus_capacity": 3, "leftover_bounds": []}
        self.workspace.generate(
            {"template": template, "packet_count": 2, "solvers": ["baseline"],
             "similarities": ["balanced-tfidf"], "baseline_samples": 3}
        )
        result = self.workspace.tune_weights({"seeds": 1, "holdout": 1, "time_limit": 0.001})
        self.assertTrue(result["truncated"])
        self.assertLess(result["evaluated_candidates"], 33)

    def test_rerun_requires_a_build(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.rerun({})

    def test_rerun_with_judgments_separates_flagged_pairs(self) -> None:
        self._flag_top_conflicts("baseline")
        result = self.workspace.rerun({"separate_flagged": False})
        info = result["rerun"]
        self.assertEqual(info["similar_labels"], 3)
        self.assertEqual((info["flagged_before"], info["flagged_after"]), (3, 0))
        self.assertTrue(result["judgments"]["use_judgments"])
        self.assertEqual(result["draft"]["report"]["hard_errors"], [])

    @unittest.skipIf(cpsat_solver.cp_model is None, "OR-Tools is not installed")
    def test_rerun_hard_separation_with_cpsat(self) -> None:
        self._flag_top_conflicts("cpsat")
        info = self.workspace.rerun({"separate_flagged": True})["rerun"]
        self.assertEqual(info["flagged_after"], 0)

    def test_comparison_review_audit_and_export_round_trip(self) -> None:
        result = self.workspace.generate(
            {
                "template": tiny_template(),
                "packet_count": 1,
                "seed": 7,
                "solvers": ["baseline"],
                "similarities": ["balanced-tfidf", "topics-only"],
            }
        )
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(result["draft"]["report"]["seed"], 7)

        audit = self.workspace.audit(
            "This proposed packet contains too much 20th century material. Investigate that"
        )
        self.assertEqual(audit["interpretation"]["kind"], "century")
        self.assertFalse(audit["needs_clarification"])
        self.assertEqual(audit["composition"][0]["pool_share"], 1.0)
        self.assertEqual(audit["composition"][0]["tag_coverage"], 0.5)
        self.assertTrue(audit["likely_conflicts"])

        with self.assertRaisesRegex(WorkspaceError, "known questions exactly once"):
            self.workspace.review([{"tossups": ["not-in-pool"], "bonuses": ["b-1"]}])

        reviewed = self.workspace.review(
            [{"tossups": ["tu-1"], "bonuses": ["b-1"]}]
        )
        self.assertEqual(reviewed["draft"]["report"]["hard_errors"], [])
        exported = self.workspace.export()
        self.assertEqual(len(exported["files"]), 1)
        self.assertEqual(exported["files"][0]["mime_type"], "application/json")

        with tempfile.TemporaryDirectory() as output:
            Path(output, exported["files"][0]["filename"]).write_text(
                exported["files"][0]["content"], encoding="utf-8"
            )
            imported = load_question_set(output)
        self.assertEqual(imported.metadata, tiny_pool().metadata)
        self.assertEqual(len(imported.packets), 1)
        self.assertEqual(imported.packets[0].tossups[0].question_id, "tu-1")

    def test_document_export_formats_and_selection_validation(self) -> None:
        self.workspace.generate(
            {
                "template": tiny_template(),
                "packet_count": 1,
                "solvers": ["baseline"],
                "similarities": ["balanced-tfidf"],
            }
        )
        exported = self.workspace.export(
            {
                "formats": ["docx", "pdf"],
                "selection": {"include_answers": False},
            }
        )
        self.assertEqual([file["filename"].rsplit(".", 1)[-1] for file in exported["files"]], ["docx", "pdf"])
        self.assertTrue(
            base64.b64decode(exported["files"][0]["content_base64"]).startswith(b"PK")
        )
        self.assertTrue(
            base64.b64decode(exported["files"][1]["content_base64"]).startswith(b"%PDF-")
        )
        bundle = self.workspace.export({"formats": ["json", "docx", "pdf"], "zip": True})
        self.assertEqual(len(bundle["files"]), 1)
        self.assertTrue(bundle["files"][0]["filename"].endswith(".zip"))
        self.assertEqual(bundle["packet_file_count"], 3)
        import io, zipfile
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(bundle["files"][0]["content_base64"]))) as archive:
            self.assertEqual(
                sorted(name.rsplit(".", 1)[-1] for name in archive.namelist()),
                ["docx", "json", "pdf"],
            )
            self.assertTrue(archive.read([n for n in archive.namelist() if n.endswith(".pdf")][0]).startswith(b"%PDF-"))
        for invalid in (
            {"formats": []},
            {"formats": ["html"]},
            {"formats": ["json", "json"]},
            {"selection": {"unknown": True}},
            {"authors": {"question-id": 1}},
            [],
        ):
            with self.assertRaises(WorkspaceError):
                self.workspace.export(invalid)

    def test_upload_imports_the_combined_bom_csv(self) -> None:
        sample_csv = (
            Path(__file__).resolve().parents[1]
            / "Test Questions"
            / "2025 ACF Winter Question Pool.csv"
        )
        content = sample_csv.read_text(encoding="utf-8-sig")
        workspace = Workspace(templates_dir=tempfile.mkdtemp(), labels_path=Path(tempfile.mkdtemp()) / "labels.jsonl")
        pool = workspace.import_csv(content, sample_csv.name)
        self.assertEqual(pool["tossup_count"], 330)
        self.assertEqual(pool["bonus_count"], 331)

    def test_invalid_hard_rules_block_export_but_remain_visible(self) -> None:
        self.workspace.generate(
            {
                "template": tiny_template(),
                "packet_count": 1,
                "solvers": ["baseline"],
                "similarities": ["balanced-tfidf"],
            }
        )
        result = self.workspace.review([{"tossups": [], "bonuses": ["b-1"]}])
        self.assertTrue(result["draft"]["report"]["hard_errors"])
        with self.assertRaisesRegex(WorkspaceError, "Resolve hard-rule violations"):
            self.workspace.export()

    def test_unrecognized_audit_request_asks_for_clarification(self) -> None:
        self.workspace.generate(
            {
                "template": tiny_template(),
                "packet_count": 1,
                "solvers": ["baseline"],
                "similarities": ["balanced-tfidf"],
            }
        )
        result = self.workspace.audit("Investigate this packet")
        self.assertTrue(result["needs_clarification"])
        self.assertIn("could not identify", result["clarification"])

    def test_century_detection_and_hyphenated_audit_request(self) -> None:
        self.assertEqual(detect_century("Events in the 20th-century"), 20)
        self.assertEqual(detect_century("The date was 2000"), 20)
        self.assertEqual(detect_century("The date was 2001"), 21)
        self.workspace.generate(
            {
                "template": tiny_template(),
                "packet_count": 1,
                "solvers": ["baseline"],
                "similarities": ["balanced-tfidf"],
            }
        )
        result = self.workspace.audit("too much 20th-century material")
        self.assertEqual(result["interpretation"]["century"], 20)

    def test_local_server_serves_ui_and_exposes_solver_availability(self) -> None:
        server = WorkspaceServer(0, self.workspace)
        with server:
            import threading

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = urlopen(f"http://127.0.0.1:{server.server_port}/")
                self.assertEqual(root.status, 200)
                self.assertIn("QTPP Packet Workshop", root.read().decode("utf-8"))
                options = urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/options"
                )
                self.assertEqual(options.status, 200)
                self.assertIn("solvers", options.read().decode("utf-8"))
                css = urlopen(f"http://127.0.0.1:{server.server_port}/app.css")
                self.assertEqual(css.status, 200)
                self.assertNotIn("fonts.googleapis.com", css.read().decode("utf-8"))
                self._post(
                    server.server_port,
                    "/api/generate",
                    {
                        "template": tiny_template(),
                        "packet_count": 1,
                        "seed": 7,
                        "solvers": ["baseline"],
                        "similarities": ["balanced-tfidf"],
                    },
                )
                audit = self._post(
                    server.server_port,
                    "/api/audit",
                    {"request": "too much 20th century material"},
                )
                self.assertEqual(audit["interpretation"]["century"], 20)
                exported = self._post(server.server_port, "/api/export", {})
                self.assertEqual(len(exported["files"]), 1)
                document_export = self._post(
                    server.server_port,
                    "/api/export",
                    {"formats": ["docx", "pdf"]},
                )
                self.assertEqual(len(document_export["files"]), 2)
                self.assertEqual(document_export["files"][1]["mime_type"], "application/pdf")
            finally:
                server.shutdown()
                thread.join(timeout=2)

    @staticmethod
    def _post(port: int, route: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"http://127.0.0.1:{port}{route}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

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
        self.workspace = Workspace(templates_dir=tempfile.mkdtemp())
        self.workspace._set_pool(tiny_pool())

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

        with tempfile.TemporaryDirectory() as output:
            Path(output, exported["files"][0]["filename"]).write_text(
                exported["files"][0]["content"], encoding="utf-8"
            )
            imported = load_question_set(output)
        self.assertEqual(imported.metadata, tiny_pool().metadata)
        self.assertEqual(len(imported.packets), 1)
        self.assertEqual(imported.packets[0].tossups[0].question_id, "tu-1")

    def test_upload_imports_the_combined_bom_csv(self) -> None:
        sample_csv = (
            Path(__file__).resolve().parents[1]
            / "Test Questions"
            / "2025 ACF Winter"
            / "Question Pool.csv"
        )
        content = sample_csv.read_text(encoding="utf-8-sig")
        workspace = Workspace(templates_dir=tempfile.mkdtemp())
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

from __future__ import annotations

import json
import re
import tempfile
import threading
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import cpsat_solver
from .build_spec import PacketBuildSpec
from .generation import GeneratedPackets, generate_packets
from .json_export import packet_filename, packet_to_dict
from .model import Bonus, Packet, QuestionPlacement, QuestionSet, Tossup
from .baseline_stats import (
    DEFAULT_SAMPLES,
    MAX_SAMPLES,
    baseline_stats,
    normalize,
    sample_random_layouts,
)
from .judged_scorer import (
    HARD_FLOOR,
    SOFT_FLOOR,
    JudgedPairScorer,
    Judgments,
    flagged_pairs_from_layouts,
    load_judgments,
)
from .weight_sweep import DEFAULT_FACTORS, sweep_weights
from .label_store import DEFAULT_LABELS, append_label, label_summary, load_labels, pair_key
from .scoring import PacketLayout, SoftWeights, score_layouts
from .similarity import SimilarityWeights, build_similarity, question_text
from .solving import InfeasibleError, PoolIndex, validate_layouts
from .template_json import load_template, template_from_dict, template_to_dict
from .time_place import detect_century
from .templates import BuildTemplate


DEFAULT_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
DEFAULT_DEMO = (
    Path(__file__).resolve().parent.parent
    / "Test Questions"
    / "2025 ACF Winter"
    / "Question Pool.csv"
)

SIMILARITY_OPTIONS: dict[str, SimilarityWeights] = {
    "balanced-tfidf": SimilarityWeights(),
    "text-only-tfidf": SimilarityWeights(text=1.0, subcategory=0.0, category=0.0),
    "topics-only": SimilarityWeights(text=0.0, subcategory=0.7, category=0.3),
}


class WorkspaceError(ValueError):
    """A user-correctable workspace request error."""


@dataclass(slots=True)
class _Run:
    generated: GeneratedPackets
    spec: PacketBuildSpec
    scorer: Any
    weights: SoftWeights
    similarity_id: str
    base_scorer: Any = None
    cross_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    normalized: dict[str, Any] = field(default_factory=dict)


class Workspace:
    """In-memory state and engine orchestration for one local browser session."""

    def __init__(
        self,
        templates_dir: str | Path = DEFAULT_TEMPLATES,
        demo_csv: str | Path = DEFAULT_DEMO,
        labels_path: str | Path = DEFAULT_LABELS,
    ) -> None:
        self._labels_path = Path(labels_path)
        self.templates_dir = Path(templates_dir)
        self.demo_csv = Path(demo_csv)
        self._lock = threading.RLock()
        self._pool: QuestionSet | None = None
        self._template: BuildTemplate | None = None
        self._runs: list[_Run] = []
        self._baseline: dict[str, dict[str, float]] = {}
        self._last_request: dict[str, Any] | None = None
        self._judgment_info: dict[str, Any] | None = None
        self._selected_run = 0
        self._draft: QuestionSet | None = None
        self._review_errors: tuple[str, ...] = ()

    def options(self) -> dict[str, Any]:
        return {
            "solvers": [
                {"id": "baseline", "label": "Python baseline", "available": True},
                {
                    "id": "cpsat",
                    "label": "OR-Tools CP-SAT",
                    "available": cpsat_solver.cp_model is not None,
                    "install": "pip install -r requirements-dev.txt",
                },
            ],
            "similarities": [
                {"id": key, "label": label}
                for key, label in (
                    ("balanced-tfidf", "Balanced TF-IDF + topic labels"),
                    ("text-only-tfidf", "Text-only TF-IDF"),
                    ("topics-only", "Topic labels only"),
                )
            ],
        }

    def templates(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(self.templates_dir.glob("*.json")):
            template = load_template(path)
            result.append(
                {
                    "id": path.name,
                    "name": template.name,
                    "template": template_to_dict(template),
                }
            )
        return result

    def import_demo(self) -> dict[str, Any]:
        if not self.demo_csv.is_file():
            raise WorkspaceError(f"Demo CSV does not exist: {self.demo_csv}")
        pool = self._load_csv_path(self.demo_csv)
        return self._set_pool(pool)

    def import_csv(self, content: str, filename: str = "question-pool.csv") -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise WorkspaceError("Choose a non-empty CSV file.")
        if not isinstance(filename, str) or not filename:
            filename = "question-pool.csv"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", suffix=".csv", delete=False
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        try:
            pool = self._load_csv_path(temporary_path)
        except (OSError, ValueError) as error:
            raise WorkspaceError(f"{filename}: {error}") from error
        finally:
            temporary_path.unlink(missing_ok=True)
        return self._set_pool(pool)

    def import_json(self, content: str, filename: str = "question-pool.json") -> dict[str, Any]:
        from .pool_json_import import parse_question_pool_json

        if not isinstance(content, str) or not content.strip():
            raise WorkspaceError("Choose a non-empty JSON file.")
        if not isinstance(filename, str) or not filename:
            filename = "question-pool.json"
        try:
            pool = parse_question_pool_json(content, filename)
        except (OSError, ValueError) as error:
            raise WorkspaceError(str(error)) from error
        return self._set_pool(pool)

    @staticmethod
    def _load_csv_path(path: Path) -> QuestionSet:
        from .csv_import import load_question_pool_csv

        try:
            return load_question_pool_csv(path)
        except (OSError, ValueError) as error:
            raise WorkspaceError(str(error)) from error

    def _set_pool(self, pool: QuestionSet) -> dict[str, Any]:
        with self._lock:
            self._pool = pool
            self._template = None
            self._runs = []
            self._baseline = {}
            self._last_request = None
            self._judgment_info = None
            self._selected_run = 0
            self._draft = None
            self._review_errors = ()
            return self.pool_summary()

    def pool_summary(self) -> dict[str, Any]:
        with self._lock:
            pool = self._require_pool()
            categories: dict[str, set[str]] = {}
            counts: dict[str, dict[str, int]] = {}
            for kind, questions in (("tossups", pool.tossups), ("bonuses", pool.bonuses)):
                for question in questions:
                    topic = question.metadata.topic
                    categories.setdefault(topic.category, set()).add(topic.subcategory)
                    entry = counts.setdefault(topic.category, {"tossups": 0, "bonuses": 0})
                    entry[kind] += 1
            return {
                "metadata": {
                    "id": pool.metadata.id,
                    "name": pool.metadata.name,
                    "year": pool.metadata.year,
                    "standard": pool.metadata.standard,
                },
                "tossup_count": len(pool.tossups),
                "bonus_count": len(pool.bonuses),
                "categories": {
                    category: sorted(subcategories)
                    for category, subcategories in sorted(categories.items())
                },
                "category_counts": {category: counts[category] for category in sorted(counts)},
            }

    def feasibility(self, template_data: Any, packet_count: Any) -> dict[str, Any]:
        from dataclasses import replace

        from .build_spec import CountSelector
        from .feasibility import check_pool_feasibility, max_feasible_packets, pool_counts

        with self._lock:
            pool = self._require_pool()
            try:
                if not isinstance(template_data, dict):
                    raise ValueError("Select or create a valid packet template.")
                template = template_from_dict(template_data)
                count = _positive_integer(packet_count, "packet_count")
                spec = template.create_spec(count)
            except (KeyError, TypeError, ValueError) as error:
                raise WorkspaceError(str(error)) from error
            counts = pool_counts(pool)
            rows = []
            for question_type, capacity in (
                ("tossup", spec.tossup_capacity),
                ("bonus", spec.bonus_capacity),
            ):
                have = sum(c for key, c in counts.items() if key.question_type == question_type)
                rows.append(
                    {"label": f"All {question_type}s", "needed": capacity * count, "available": have}
                )
            for quota in spec.quotas:
                selector: CountSelector = quota.selector
                have = sum(c for key, c in counts.items() if selector.matches(key))
                rows.append(
                    {
                        "label": " / ".join(
                            part
                            for part in (selector.question_type, selector.category, selector.subcategory)
                            if part
                        ),
                        "needed": quota.minimum * count,
                        "available": have,
                    }
                )
            for row in rows:
                row["ok"] = row["available"] >= row["needed"]
            errors = check_pool_feasibility(pool, spec)
            max_packets = max_feasible_packets(pool, replace(spec, packet_count=1))
            return {
                "feasible": not errors,
                "errors": list(errors),
                "max_packets": max_packets,
                "requirements": rows,
            }

    def suggest_template(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .template_wizard import suggest_template

        with self._lock:
            pool = self._require_pool()
            try:
                template = suggest_template(
                    pool,
                    name=str(request.get("name") or "Suggested template"),
                    packet_count=_positive_integer(request.get("packet_count"), "packet_count"),
                    tossup_capacity=_integer(request.get("tossup_capacity"), "tossup_capacity"),
                    bonus_capacity=_integer(request.get("bonus_capacity"), "bonus_capacity"),
                    tolerance=_integer(request.get("tolerance", 1), "tolerance"),
                )
            except (TypeError, ValueError) as error:
                raise WorkspaceError(str(error)) from error
            return {"template": template_to_dict(template)}

    def generate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._generate(request)

    def rerun(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Rebuild with the last settings, applying saved similarity judgments."""
        with self._lock:
            if self._last_request is None or not self._runs or self._draft is None:
                raise WorkspaceError("Generate packets before re-running with judgments.")
            pool = self._require_pool()
            selected_before = self._selected_run
            layouts_before = _layouts_from_question_set(self._draft)
            judgments = load_judgments(self._labels_path, _questions_by_id(pool))
            separate = bool(request.get("separate_flagged", False))
            self._generate(
                {**self._last_request, "use_judgments": True, "separate_flagged": separate}
            )
            payload = self._select_run(min(selected_before, len(self._runs) - 1))
            payload["rerun"] = {
                "similar_labels": len(judgments.similar),
                "different_labels": len(judgments.different),
                "flagged_before": flagged_pairs_from_layouts(judgments, layouts_before),
                "flagged_after": flagged_pairs_from_layouts(
                    judgments, _layouts_from_question_set(self._draft)
                ),
                "separate": separate,
            }
            return payload

    def _generate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        pool = self._require_pool()
        template_data = request.get("template")
        if not isinstance(template_data, dict):
            raise WorkspaceError("Select or create a valid packet template.")
        try:
            template = template_from_dict(template_data)
            packet_count = _positive_integer(request.get("packet_count"), "packet_count")
            spec = template.create_spec(packet_count)
            solver_ids = _string_list(request.get("solvers"), "solvers")
            similarity_ids = _string_list(request.get("similarities"), "similarities")
            seed = _integer(request.get("seed", 0), "seed")
            baseline_samples = _integer(
                request.get("baseline_samples", DEFAULT_SAMPLES), "baseline_samples"
            )
            if not 1 <= baseline_samples <= MAX_SAMPLES:
                raise ValueError(
                    f"baseline_samples must be between 1 and {MAX_SAMPLES}."
                )
        except (KeyError, TypeError, ValueError) as error:
            raise WorkspaceError(str(error)) from error
        if not solver_ids or not similarity_ids:
            raise WorkspaceError("Select at least one solver and one similarity scorer.")
        unknown_solvers = sorted(set(solver_ids) - {"baseline", "cpsat"})
        unknown_similarities = sorted(set(similarity_ids) - SIMILARITY_OPTIONS.keys())
        if unknown_solvers or unknown_similarities:
            raise WorkspaceError(
                f"Unknown options: {', '.join((*unknown_solvers, *unknown_similarities))}"
            )
        if "cpsat" in solver_ids and cpsat_solver.cp_model is None:
            raise WorkspaceError(
                "CP-SAT is unavailable; install the optional dependencies with "
                "`pip install -r requirements-dev.txt`."
            )
        try:
            weights = _soft_weights(request.get("soft_weights"))
        except (TypeError, ValueError) as error:
            raise WorkspaceError(str(error)) from error
        runs: list[_Run] = []
        use_judgments = bool(request.get("use_judgments", False))
        separate = use_judgments and bool(request.get("separate_flagged", False))
        judgments = (
            load_judgments(self._labels_path, _questions_by_id(pool))
            if use_judgments
            else Judgments()
        )
        base_scorers = {
            similarity_id: build_similarity(pool, SIMILARITY_OPTIONS[similarity_id])
            for similarity_id in dict.fromkeys(similarity_ids)
        }
        # Scores and baselines always use the soft floor so penalties stay comparable;
        # separation only changes what the solvers optimize.
        scorers = {
            key: JudgedPairScorer(scorer, judgments, SOFT_FLOOR)
            for key, scorer in base_scorers.items()
        }
        solving_scorers = (
            {
                key: JudgedPairScorer(scorer, judgments, HARD_FLOOR)
                for key, scorer in base_scorers.items()
            }
            if separate
            else scorers
        )
        for solver_id in solver_ids:
            for similarity_id in similarity_ids:
                pair_scorer = scorers[similarity_id]
                options: dict[str, Any] = {}
                if separate and solver_id == "cpsat":
                    options["separate"] = sorted(judgments.similar)
                try:
                    generated = generate_packets(
                        pool,
                        spec,
                        solving_scorers[similarity_id],
                        weights,
                        solver=solver_id,
                        seed=seed,
                        **options,
                    )
                except (InfeasibleError, RuntimeError, ValueError) as error:
                    raise WorkspaceError(f"{solver_id} / {similarity_id}: {error}") from error
                runs.append(
                    _Run(
                        generated,
                        spec,
                        pair_scorer,
                        weights,
                        similarity_id,
                        base_scorers[similarity_id],
                    )
                )
        category_of = PoolIndex.from_pool(pool).category_of
        for run in runs:
            layouts = _layouts_from_question_set(run.generated.question_set)
            # Re-score every layout with every selected scorer so runs can be
            # compared on one common yardstick.
            run.cross_scores = {
                similarity_id: _score_dict(
                    score_layouts(layouts, category_of, scorer, weights)
                )
                for similarity_id, scorer in scorers.items()
            }
        try:
            stats = baseline_stats(
                pool,
                sample_random_layouts(pool, spec, baseline_samples, seed),
                scorers,
                weights,
            )
        except (InfeasibleError, ValueError) as error:
            raise WorkspaceError(f"Random baseline failed: {error}") from error
        for run in runs:
            run.normalized = normalize(
                {key: value["total"] for key, value in run.cross_scores.items()}, stats
            )
        self._baseline = {
            key: {"mean": stat.mean, "stdev": stat.stdev, "samples": stat.samples}
            for key, stat in stats.items()
        }
        self._last_request = dict(request)
        self._judgment_info = {
            "use_judgments": use_judgments,
            "separate": separate,
            "similar": len(judgments.similar),
            "different": len(judgments.different),
        }
        self._template = template
        self._runs = runs
        self._selected_run = 0
        self._draft = runs[0].generated.question_set
        self._review_errors = ()
        return self._workspace_payload()

    def weight_sweep(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Show how sensitive the selected build is to each soft-score weight."""
        with self._lock:
            pool = self._require_pool()
            run = self._require_run()
            try:
                weights = (
                    _soft_weights(request["soft_weights"])
                    if request.get("soft_weights") is not None
                    else run.weights
                )
                factors = request.get("factors", DEFAULT_FACTORS)
                if not isinstance(factors, (list, tuple)) or any(
                    isinstance(item, bool) or not isinstance(item, (int, float)) for item in factors
                ):
                    raise ValueError("factors must be a list of numbers.")
                result = sweep_weights(
                    pool,
                    run.spec,
                    run.scorer,
                    weights,
                    seed=run.generated.report.seed,
                    factors=factors,
                )
            except InfeasibleError as error:
                raise WorkspaceError(str(error)) from error
            except (TypeError, ValueError) as error:
                raise WorkspaceError(str(error)) from error
            result["similarity"] = _similarity_name(run.similarity_id)
            return result

    def select_run(self, index: int) -> dict[str, Any]:
        with self._lock:
            return self._select_run(index)

    def _select_run(self, index: int) -> dict[str, Any]:
        if not isinstance(index, int) or isinstance(index, bool):
            raise WorkspaceError("run_index must be an integer.")
        if index < 0 or index >= len(self._runs):
            raise WorkspaceError("Selected comparison result no longer exists.")
        self._selected_run = index
        self._draft = self._runs[index].generated.question_set
        self._review_errors = ()
        return self._workspace_payload()

    def review(self, layouts_data: Any) -> dict[str, Any]:
        with self._lock:
            pool = self._require_pool()
            run = self._require_run()
            if not isinstance(layouts_data, list) or len(layouts_data) != run.spec.packet_count:
                raise WorkspaceError(
                    f"Provide exactly {run.spec.packet_count} packet layouts."
                )
            layouts: list[PacketLayout] = []
            for number, layout in enumerate(layouts_data, start=1):
                if not isinstance(layout, dict):
                    raise WorkspaceError(f"Packet {number} layout must be an object.")
                tossups = _string_list(layout.get("tossups"), f"packet {number} tossups")
                bonuses = _string_list(layout.get("bonuses"), f"packet {number} bonuses")
                layouts.append(PacketLayout(tuple(tossups), tuple(bonuses)))

            index = PoolIndex.from_pool(pool)
            errors, leftovers = validate_layouts(index, run.spec, layouts)
            structural_errors = tuple(
                error
                for error in errors
                if "unknown or mistyped" in error or "assigned twice" in error
            )
            if structural_errors:
                raise WorkspaceError(
                    "Placements must reference known questions exactly once: "
                    + "; ".join(structural_errors)
                )
            if self._draft is None:
                raise WorkspaceError("There is no draft to edit.")
            packets = []
            for packet_number, layout in enumerate(layouts, start=1):
                previous = self._draft.packets[packet_number - 1]
                packets.append(
                    Packet(
                        id=previous.id,
                        name=previous.name,
                        number=previous.number,
                        tossups=tuple(
                            QuestionPlacement(question_id, position)
                            for position, question_id in enumerate(layout.tossups, start=1)
                        ),
                        bonuses=tuple(
                            QuestionPlacement(question_id, position)
                            for position, question_id in enumerate(layout.bonuses, start=1)
                        ),
                    )
                )
            from dataclasses import replace

            self._draft = replace(self._draft, packets=tuple(packets))
            self._review_errors = errors
            return self._workspace_payload(leftovers=leftovers)

    def audit(self, request: str = "") -> dict[str, Any]:
        with self._lock:
            pool = self._require_pool()
            draft = self._draft
            if draft is None:
                raise WorkspaceError("Generate packets before running an audit.")
            run = self._require_run()
            if not isinstance(request, str):
                raise WorkspaceError("Audit request must be text.")
            request = request.strip()
            target = _parse_audit_target(request, pool)
            pool_questions = _questions_by_id(pool)
            layouts = _layouts_from_question_set(draft)
            findings = _composition_findings(pool, layouts, pool_questions, target)
            conflicts = _conflict_findings(layouts, pool_questions, run, self._labels_path)
            return {
                "request": request,
                "interpretation": target,
                "needs_clarification": target["kind"] == "unsupported",
                "clarification": (
                    "I could not identify a century or category in that request. "
                    "Try a specific period such as “20th century” or a pool category."
                    if target["kind"] == "unsupported"
                    else None
                ),
                "hard_errors": list(self._review_errors),
                "leftover_count": len(
                    validate_layouts(
                        PoolIndex.from_pool(pool), run.spec, layouts
                    )[1]
                ),
                "composition": findings,
                "likely_conflicts": conflicts,
            }

    def export(self) -> dict[str, Any]:
        with self._lock:
            pool = self._require_pool()
            draft = self._draft
            if draft is None:
                raise WorkspaceError("Generate packets before exporting.")
            run = self._require_run()
            layouts = _layouts_from_question_set(draft)
            errors, _ = validate_layouts(PoolIndex.from_pool(pool), run.spec, layouts)
            if errors:
                raise WorkspaceError(
                    "Resolve hard-rule violations before export: " + "; ".join(errors)
                )
            files = []
            for packet in draft.packets:
                if not packet.tossups and not packet.bonuses:
                    raise WorkspaceError(
                        f"Packet {packet.number} is empty and cannot be exported."
                    )
                files.append(
                    {
                        "filename": packet_filename(packet),
                        "content": json.dumps(
                            packet_to_dict(draft, packet), indent=4, ensure_ascii=False
                        )
                        + "\n",
                    }
                )
            return {"files": files}

    def label_pair(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Record a human similarity judgment for two pool questions."""
        with self._lock:
            pool = self._require_pool()
            questions = {q.metadata.id: q for q in (*pool.tossups, *pool.bonuses)}
            first_id, second_id = request.get("first_id"), request.get("second_id")
            if first_id not in questions or second_id not in questions or first_id == second_id:
                raise WorkspaceError("Choose two different questions from the imported pool.")
            reviewer = request.get("reviewer", "")
            if not isinstance(reviewer, str) or len(reviewer) > 80:
                raise WorkspaceError("reviewer must be text of 80 characters or fewer.")
            first, second = questions[first_id], questions[second_id]
            kinds = "-".join(
                sorted("tossup" if isinstance(q, Tossup) else "bonus" for q in (first, second))
            )
            try:
                record = append_label(
                    self._labels_path,
                    key=pair_key(question_text(first), question_text(second)),
                    first_id=first_id,
                    second_id=second_id,
                    label=request.get("label"),
                    reviewer=reviewer,
                    pool=pool.metadata.name,
                    question_types=kinds,
                )
            except ValueError as error:
                raise WorkspaceError(str(error)) from error
            return {"label": record["label"], "summary": label_summary(load_labels(self._labels_path).values())}

    def _workspace_payload(self, leftovers: Sequence[str] | None = None) -> dict[str, Any]:
        pool = self._require_pool()
        draft = self._draft
        run = self._require_run()
        if draft is None:
            raise WorkspaceError("There is no generated draft.")
        layouts = _layouts_from_question_set(draft)
        errors, calculated_leftovers = validate_layouts(
            PoolIndex.from_pool(pool), run.spec, layouts
        )
        leftover_ids = tuple(leftovers) if leftovers is not None else calculated_leftovers
        score = score_layouts(
            layouts,
            PoolIndex.from_pool(pool).category_of,
            run.scorer,
            run.weights,
        )
        return {
            "runs": [
                {
                    "index": index,
                    "solver": item.generated.report.solver,
                    "seed": item.generated.report.seed,
                    "similarity": _similarity_name(item.similarity_id),
                    "similarity_id": item.similarity_id,
                    "cross_scores": item.cross_scores,
                    "normalized": item.normalized,
                    "seconds": item.generated.report.seconds,
                    "score": _score_dict(item.generated.report.score),
                    "leftover_count": len(item.generated.report.leftover_ids),
                    "hard_errors": [],
                }
                for index, item in enumerate(self._runs)
            ],
            "selected_run": self._selected_run,
            "judgments": self._judgment_info,
            "baseline": self._baseline,
            "yardsticks": [
                {"id": similarity_id, "name": _similarity_name(similarity_id)}
                for similarity_id in dict.fromkeys(item.similarity_id for item in self._runs)
            ],
            "pool": self.pool_summary(),
            "draft": {
                "packets": [
                    {
                        "id": packet.id,
                        "name": packet.name,
                        "number": packet.number,
                        "tossups": [placement.question_id for placement in packet.tossups],
                        "bonuses": [placement.question_id for placement in packet.bonuses],
                    }
                    for packet in draft.packets
                ],
                "questions": [
                    _question_dict(question, "tossup")
                    for question in pool.tossups
                ]
                + [_question_dict(question, "bonus") for question in pool.bonuses],
                "report": {
                    "solver": run.generated.report.solver,
                    "seed": run.generated.report.seed,
                    "seconds": run.generated.report.seconds,
                    "score": _score_dict(score),
                    "leftover_ids": list(leftover_ids),
                    "hard_errors": list(errors),
                },
            },
        }

    def _require_pool(self) -> QuestionSet:
        if self._pool is None:
            raise WorkspaceError("Import a CSV pool or load the sample demo first.")
        return self._pool

    def _require_run(self) -> _Run:
        if not self._runs:
            raise WorkspaceError("Generate packets before continuing.")
        return self._runs[self._selected_run]


def _positive_integer(value: Any, label: str) -> int:
    number = _integer(value, label)
    if number < 1:
        raise ValueError(f"{label} must be a positive integer.")
    return number


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be an array of strings.")
    return value


def _soft_weights(value: Any) -> SoftWeights:
    if value is None:
        return SoftWeights()
    if not isinstance(value, dict):
        raise ValueError("soft_weights must be an object.")
    return SoftWeights(
        adjacent_category=value.get("adjacent_category", 1.0),
        same_packet=value.get("same_packet", 1.0),
        nearby=value.get("nearby", 3.0),
        window=value.get("window", 3),
    )


def _questions_by_id(pool: QuestionSet) -> dict[str, Tossup | Bonus]:
    return {
        question.metadata.id: question
        for question in (*pool.tossups, *pool.bonuses)
    }


def _layouts_from_question_set(question_set: QuestionSet) -> list[PacketLayout]:
    return [
        PacketLayout(
            tuple(item.question_id for item in packet.tossups),
            tuple(item.question_id for item in packet.bonuses),
        )
        for packet in question_set.packets
    ]


def _question_dict(question: Tossup | Bonus, question_type: str) -> dict[str, Any]:
    topic = question.metadata.topic
    record: dict[str, Any] = {
        "id": question.metadata.id,
        "type": question_type,
        "category": topic.category,
        "subcategory": topic.subcategory,
        "alternate_subcategory": topic.alternate_subcategory,
    }
    if isinstance(question, Tossup):
        record.update(
            question=question.question,
            answer=question.answer,
            text=question.question_sanitized or question.question,
        )
    else:
        record.update(
            leadin=question.leadin,
            parts=[
                {"question": part.question, "answer": part.answer}
                for part in question.parts
            ],
            text=" ".join(
                [question.leadin, *(part.question for part in question.parts)]
            ),
        )
    return record


def _score_dict(score: Any) -> dict[str, float]:
    return {
        "adjacent_category": score.adjacent_category,
        "same_packet": score.same_packet,
        "nearby": score.nearby,
        "total": score.total,
    }


def _similarity_name(similarity_id: str) -> str:
    return {
        "balanced-tfidf": "Balanced TF-IDF + topic labels",
        "text-only-tfidf": "Text-only TF-IDF",
        "topics-only": "Topic labels only",
    }[similarity_id]


def _parse_audit_target(request: str, pool: QuestionSet) -> dict[str, Any]:
    century = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)[-\s]+centur(?:y|ies)\b", request, re.I
    )
    categories = sorted(
        {question.metadata.topic.category for question in (*pool.tossups, *pool.bonuses)},
        key=len,
        reverse=True,
    )
    category = next(
        (name for name in categories if re.search(rf"\b{re.escape(name)}\b", request, re.I)),
        None,
    )
    if century:
        return {
            "kind": "century",
            "century": int(century.group(1)),
            "category": category,
            "label": f"{century.group(1)}{_ordinal_suffix(int(century.group(1)))} century",
        }
    if category:
        return {"kind": "category", "category": category, "label": category}
    return {"kind": "unsupported", "category": None, "label": None}


def _ordinal_suffix(number: int) -> str:
    if 10 <= number % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")


def _composition_findings(
    pool: QuestionSet,
    layouts: Sequence[PacketLayout],
    questions: Mapping[str, Tossup | Bonus],
    target: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if target.get("kind") not in {"century", "category"}:
        return []

    def matches(question: Tossup | Bonus) -> bool:
        if target.get("category") and (
            question.metadata.topic.category.casefold()
            != str(target["category"]).casefold()
        ):
            return False
        if target["kind"] == "category":
            return True
        return detect_century(question_text(question)) == target["century"]

    scoped_pool = [
        question for question in questions.values()
        if not target.get("category")
        or question.metadata.topic.category.casefold()
        == str(target["category"]).casefold()
    ]
    eligible_pool = (
        [
            question
            for question in scoped_pool
            if detect_century(question_text(question)) is not None
        ]
        if target["kind"] == "century"
        else scoped_pool
    )
    tagged_pool = [question for question in eligible_pool if matches(question)]
    pool_rate = len(tagged_pool) / len(eligible_pool) if eligible_pool else 0.0
    per_packet = []
    tagged_total = 0
    eligible_total = 0
    scoped_total = 0
    for packet_number, layout in enumerate(layouts, start=1):
        assigned = [questions[qid] for qid in (*layout.tossups, *layout.bonuses) if qid in questions]
        scoped = [
            question
            for question in assigned
            if not target.get("category")
            or question.metadata.topic.category.casefold()
            == str(target["category"]).casefold()
        ]
        relevant = (
            [
                question
                for question in scoped
                if detect_century(question_text(question)) is not None
            ]
            if target["kind"] == "century"
            else scoped
        )
        target_count = sum(1 for question in relevant if matches(question))
        rate = target_count / len(relevant) if relevant else 0.0
        tagged_total += target_count
        eligible_total += len(relevant)
        scoped_total += len(scoped)
        per_packet.append(
            {
                "packet": packet_number,
                "target_count": target_count,
                "eligible_count": len(relevant),
                "scoped_count": len(scoped),
                "tag_coverage": round(len(relevant) / len(scoped), 4) if scoped else 0.0,
                "share": round(rate, 4),
                "difference_from_pool": round(rate - pool_rate, 4),
                "question_ids": [
                    question.metadata.id
                    for question in relevant
                    if matches(question)
                ],
            }
        )
    peer_mean = (
        sum(item["share"] for item in per_packet) / len(per_packet)
        if per_packet
        else 0.0
    )
    for item in per_packet:
        item["difference_from_peer_mean"] = round(item["share"] - peer_mean, 4)
    per_packet.sort(
        key=lambda item: (
            item["difference_from_pool"],
            item["difference_from_peer_mean"],
        ),
        reverse=True,
    )
    return [
        {
            "label": target["label"],
            "pool_target_count": len(tagged_pool),
            "pool_eligible_count": len(eligible_pool),
            "pool_scoped_count": len(scoped_pool),
            "pool_share": round(pool_rate, 4),
            "tag_coverage": (
                round(len(eligible_pool) / len(scoped_pool), 4)
                if scoped_pool
                else 0.0
            ),
            "packet_target_count": tagged_total,
            "packet_eligible_count": eligible_total,
            "packet_scoped_count": scoped_total,
            "peer_mean_share": round(peer_mean, 4),
            "packets": per_packet,
            "note": (
                "Comparative signal only; no numeric threshold was specified. "
                "Review the counts and question IDs before treating a difference as a conflict."
            ),
        }
    ]


def _conflict_side(
    question_id: str,
    questions: Mapping[str, Tossup | Bonus],
    positions: Mapping[str, tuple[str, int]],
) -> dict[str, Any]:
    kind, number = positions[question_id]
    return {**_question_dict(questions[question_id], kind), "number": number}


def _conflict_findings(
    layouts: Sequence[PacketLayout],
    questions: Mapping[str, Tossup | Bonus],
    run: _Run,
    labels_path: Path | None = None,
) -> list[dict[str, Any]]:
    categories = {
        question_id: question.metadata.topic.category
        for question_id, question in questions.items()
    }
    candidates: list[dict[str, Any]] = []
    scorer = run.base_scorer or run.scorer
    positions = {
        number: {
            **{qid: ("tossup", i) for i, qid in enumerate(layout.tossups, start=1)},
            **{qid: ("bonus", i) for i, qid in enumerate(layout.bonuses, start=1)},
        }
        for number, layout in enumerate(layouts, start=1)
    }
    for packet_number, layout in enumerate(layouts, start=1):
        assigned = (*layout.tossups, *layout.bonuses)
        for first, second in combinations(assigned, 2):
            if first not in questions or second not in questions:
                continue
            value = scorer.score(first, second)
            candidates.append(
                {
                    "packet": packet_number,
                    "first_id": first,
                    "second_id": second,
                    "similarity": round(value, 4),
                    "shared_category": categories[first] == categories[second],
                    "reason": "High pairwise text/topic similarity; review for repeated material.",
                }
            )
        for first, second in zip(layout.tossups, layout.tossups[1:]):
            if first in categories and second in categories and categories[first] == categories[second]:
                candidates.append(
                    {
                        "packet": packet_number,
                        "first_id": first,
                        "second_id": second,
                        "similarity": round(scorer.score(first, second), 4),
                        "shared_category": True,
                        "reason": "Adjacent tossups share a category.",
                    }
                )
    candidates.sort(
        key=lambda item: (
            item["similarity"],
            item["shared_category"],
            item["reason"].startswith("Adjacent"),
        ),
        reverse=True,
    )
    unique: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str, str]] = set()
    stored = load_labels(labels_path) if labels_path else {}
    for item in candidates:
        pair = tuple(sorted((item["first_id"], item["second_id"])))
        key = (item["packet"], pair[0], pair[1], item["reason"])
        if key not in seen:
            seen.add(key)
            item["first"] = _conflict_side(item["first_id"], questions, positions[item["packet"]])
            item["second"] = _conflict_side(item["second_id"], questions, positions[item["packet"]])
            if stored:
                known = stored.get(
                    pair_key(
                        question_text(questions[item["first_id"]]),
                        question_text(questions[item["second_id"]]),
                    )
                )
                item["saved_label"] = known["label"] if known else None
            unique.append(item)
        if len(unique) == 20:
            break
    return unique

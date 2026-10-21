from __future__ import annotations

import json
import re
import tempfile
import threading
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import cpsat_solver
from .build_spec import PacketBuildSpec
from .generation import GeneratedPackets, generate_packets
from .json_export import packet_filename, packet_to_dict
from .model import Bonus, Packet, QuestionPlacement, QuestionSet, Tossup
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


class Workspace:
    """In-memory state and engine orchestration for one local browser session."""

    def __init__(
        self,
        templates_dir: str | Path = DEFAULT_TEMPLATES,
        demo_csv: str | Path = DEFAULT_DEMO,
    ) -> None:
        self.templates_dir = Path(templates_dir)
        self.demo_csv = Path(demo_csv)
        self._lock = threading.RLock()
        self._pool: QuestionSet | None = None
        self._template: BuildTemplate | None = None
        self._runs: list[_Run] = []
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

    def generate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
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
            for solver_id in solver_ids:
                for similarity_id in similarity_ids:
                    pair_scorer = build_similarity(
                        pool, SIMILARITY_OPTIONS[similarity_id]
                    )
                    try:
                        generated = generate_packets(
                            pool,
                            spec,
                            pair_scorer,
                            weights,
                            solver=solver_id,
                            seed=seed,
                        )
                    except (InfeasibleError, RuntimeError, ValueError) as error:
                        raise WorkspaceError(f"{solver_id} / {similarity_id}: {error}") from error
                    runs.append(
                        _Run(generated, spec, pair_scorer, weights, similarity_id)
                    )
            self._template = template
            self._runs = runs
            self._selected_run = 0
            self._draft = runs[0].generated.question_set
            self._review_errors = ()
            return self._workspace_payload()

    def select_run(self, index: int) -> dict[str, Any]:
        with self._lock:
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
            conflicts = _conflict_findings(layouts, pool_questions, run)
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
                    "seconds": item.generated.report.seconds,
                    "score": _score_dict(item.generated.report.score),
                    "leftover_count": len(item.generated.report.leftover_ids),
                    "hard_errors": [],
                }
                for index, item in enumerate(self._runs)
            ],
            "selected_run": self._selected_run,
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


def _conflict_findings(
    layouts: Sequence[PacketLayout],
    questions: Mapping[str, Tossup | Bonus],
    run: _Run,
) -> list[dict[str, Any]]:
    categories = {
        question_id: question.metadata.topic.category
        for question_id, question in questions.items()
    }
    candidates: list[dict[str, Any]] = []
    for packet_number, layout in enumerate(layouts, start=1):
        assigned = (*layout.tossups, *layout.bonuses)
        for first, second in combinations(assigned, 2):
            if first not in questions or second not in questions:
                continue
            value = run.scorer.score(first, second)
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
                        "similarity": round(run.scorer.score(first, second), 4),
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
    for item in candidates:
        pair = tuple(sorted((item["first_id"], item["second_id"])))
        key = (item["packet"], pair[0], pair[1], item["reason"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) == 20:
            break
    return unique

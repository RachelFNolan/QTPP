from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from .build_spec import (
    AggregateQuota,
    AllowedCountPatterns,
    CategoryQuota,
    CountSelector,
    LeftoverBound,
    PacketBuildSpec,
    QuestionType,
)


@dataclass(frozen=True, slots=True)
class BuildTemplate:
    name: str
    tossup_capacity: int
    bonus_capacity: int
    quotas: tuple[CategoryQuota, ...]
    allowed_patterns: tuple[AllowedCountPatterns, ...]
    leftover_bounds: tuple[LeftoverBound, ...] = (
        LeftoverBound("tossup"),
        LeftoverBound("bonus"),
    )

    def create_spec(
        self,
        packet_count: int,
        *,
        aggregate_quotas: tuple[AggregateQuota, ...] = (),
    ) -> PacketBuildSpec:
        return PacketBuildSpec(
            packet_count=packet_count,
            tossup_capacity=self.tossup_capacity,
            bonus_capacity=self.bonus_capacity,
            quotas=self.quotas,
            allowed_patterns=self.allowed_patterns,
            aggregate_quotas=aggregate_quotas,
            leftover_bounds=self.leftover_bounds,
        )


def blank_build_template(
    tossup_capacity: int, bonus_capacity: int
) -> BuildTemplate:
    """Return a constraint-free template with user-selected packet capacities."""
    return BuildTemplate(
        name="Custom / Blank",
        tossup_capacity=tossup_capacity,
        bonus_capacity=bonus_capacity,
        quotas=(),
        allowed_patterns=(),
    )


def acf_winter_submitted_template() -> BuildTemplate:
    """Return the editable ACF Winter submitted 24/24 distribution preset."""
    quotas = _fixed_quotas(
        {
            ("Literature", "American Literature"): (1, 1),
            ("Literature", "British Literature"): (1, 1),
            ("Literature", "European Literature"): (1, 1),
            ("Literature", "World Literature"): (1, 1),
            ("Literature", "Misc. Literature"): (1, 1),
            ("History", "American History"): (1, 1),
            ("History", "World History"): (1, 1),
            ("History", "Other History"): (1, 1),
            ("Science", "Biology"): (1, 1),
            ("Science", "Chemistry"): (1, 1),
            ("Science", "Physics"): (1, 1),
            ("Science", "Other Science"): (1, 1),
            ("Science", "Misc. Science"): (1, 1),
            ("Fine Arts", "Visual Fine Arts"): (1, 1),
            ("Fine Arts", "Auditory Fine Arts"): (1, 1),
            ("Fine Arts", "Other Fine Arts"): (1, 1),
            ("Religion", "Religion"): (1, 1),
            ("Mythology", "Mythology"): (1, 1),
            ("Social Science", "Social Science"): (1, 1),
            ("Philosophy", "Philosophy"): (1, 1),
        }
    )
    patterns = (
        AllowedCountPatterns(
            name="History European and Miscellaneous alternatives",
            selectors=(
                _selector("tossup", "History", "European History"),
                _selector("bonus", "History", "European History"),
                _selector("tossup", "History", "Misc. History"),
                _selector("bonus", "History", "Misc. History"),
            ),
            patterns=((2, 1, 0, 1), (1, 2, 1, 0)),
        ),
        _other_submitted_patterns(),
    )
    return BuildTemplate(
        name="ACF Winter — Submitted Full Packet",
        tossup_capacity=24,
        bonus_capacity=24,
        quotas=quotas,
        allowed_patterns=patterns,
    )


def acf_winter_final_template() -> BuildTemplate:
    """Return the editable ACF Winter final/edited 20/20 distribution preset."""
    quotas = _fixed_quotas(
        {
            ("Literature", "American Literature"): (1, 1),
            ("Literature", "British Literature"): (1, 1),
            ("Literature", "European Literature"): (1, 1),
            ("Literature", "World Literature"): (1, 1),
            ("History", "American History"): (1, 1),
            ("History", "European History"): (1, 1),
            ("History", "World History"): (1, 1),
            ("History", "Other History"): (1, 1),
            ("Science", "Biology"): (1, 1),
            ("Science", "Chemistry"): (1, 1),
            ("Science", "Physics"): (1, 1),
            ("Science", "Other Science"): (1, 1),
            ("Fine Arts", "Visual Fine Arts"): (1, 1),
            ("Fine Arts", "Auditory Fine Arts"): (1, 1),
            ("Fine Arts", "Other Fine Arts"): (1, 1),
            ("Religion", "Religion"): (1, 1),
            ("Mythology", "Mythology"): (1, 1),
            ("Social Science", "Social Science"): (1, 1),
            ("Philosophy", "Philosophy"): (1, 1),
        }
    )
    return BuildTemplate(
        name="ACF Winter — Final/Edited Packet",
        tossup_capacity=20,
        bonus_capacity=20,
        quotas=quotas,
        allowed_patterns=(_other_final_patterns(),),
    )


def _fixed_quotas(
    entries: dict[tuple[str, str], tuple[int, int]],
) -> tuple[CategoryQuota, ...]:
    return tuple(
        CategoryQuota(
            selector=_selector(question_type, category, subcategory),
            minimum=count,
            maximum=count,
        )
        for (category, subcategory), (tossups, bonuses) in entries.items()
        for question_type, count in (("tossup", tossups), ("bonus", bonuses))
    )


def _other_submitted_patterns() -> AllowedCountPatterns:
    categories = ("Geography", "Current Events", "Other Academic", "Pop Culture")
    selectors = tuple(
        _selector(question_type, category, category)
        for category in categories
        for question_type in ("tossup", "bonus")
    )
    patterns = tuple(
        tuple(value for pair in pattern for value in pair)
        for pattern in product(((1, 0), (0, 1)), repeat=len(categories))
        if (sum(value[0] for value in pattern), sum(value[1] for value in pattern))
        == (2, 2)
    )
    return AllowedCountPatterns(
        name="Submitted Other distribution alternatives",
        selectors=selectors,
        patterns=patterns,
    )


def _other_final_patterns() -> AllowedCountPatterns:
    categories = ("Geography", "Current Events", "Pop Culture", "Other Academic")
    selectors = tuple(
        _selector(question_type, category, category)
        for category in categories
        for question_type in ("tossup", "bonus")
    )
    patterns = []
    for tossup_category, bonus_category in combinations(categories, 2):
        patterns.append(
            tuple(
                int(
                    (question_type == "tossup" and category == tossup_category)
                    or (question_type == "bonus" and category == bonus_category)
                )
                for category in categories
                for question_type in ("tossup", "bonus")
            )
        )
        patterns.append(
            tuple(
                int(
                    (question_type == "bonus" and category == tossup_category)
                    or (question_type == "tossup" and category == bonus_category)
                )
                for category in categories
                for question_type in ("tossup", "bonus")
            )
        )
    return AllowedCountPatterns(
        name="Final Other: one tossup and one bonus from distinct subcategories",
        selectors=selectors,
        patterns=tuple(patterns),
    )


def _selector(
    question_type: QuestionType, category: str, subcategory: str
) -> CountSelector:
    return CountSelector(question_type, category, subcategory)

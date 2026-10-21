from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence


QuestionType = Literal["tossup", "bonus"]
RuleScope = Literal["packet", "set"]
QUESTION_TYPES: tuple[QuestionType, ...] = ("tossup", "bonus")


@dataclass(frozen=True, slots=True)
class CountSelector:
    question_type: QuestionType
    category: str
    subcategory: str | None = None

    def __post_init__(self) -> None:
        if self.question_type not in QUESTION_TYPES:
            raise ValueError("question_type must be 'tossup' or 'bonus'")
        if not self.category:
            raise ValueError("category must be a non-empty string")
        if self.subcategory is not None and not self.subcategory:
            raise ValueError("subcategory must be a non-empty string when specified")

    def matches(self, other: CountSelector) -> bool:
        return (
            self.question_type == other.question_type
            and self.category == other.category
            and (self.subcategory is None or self.subcategory == other.subcategory)
        )


@dataclass(frozen=True, slots=True)
class CategoryQuota:
    selector: CountSelector
    minimum: int = 0
    maximum: int | None = None

    def __post_init__(self) -> None:
        _validate_bounds(self.minimum, self.maximum, "category quota")


@dataclass(frozen=True, slots=True)
class AggregateQuota:
    selector: CountSelector
    minimum: int = 0
    maximum: int | None = None

    def __post_init__(self) -> None:
        _validate_bounds(self.minimum, self.maximum, "aggregate quota")


@dataclass(frozen=True, slots=True)
class AllowedCountPatterns:
    """Allowed count vectors for a set of selectors, checked per packet."""

    name: str
    selectors: tuple[CountSelector, ...]
    patterns: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("pattern rule name must be a non-empty string")
        if not self.selectors or not self.patterns:
            raise ValueError("pattern rules require selectors and at least one pattern")
        if len(set(self.selectors)) != len(self.selectors):
            raise ValueError(f"{self.name}: selectors must be unique")
        for pattern in self.patterns:
            if len(pattern) != len(self.selectors):
                raise ValueError(f"{self.name}: every pattern must match the selector count")
            if any(not _nonnegative_int(count) for count in pattern):
                raise ValueError(f"{self.name}: pattern counts must be non-negative integers")
        if len(set(self.patterns)) != len(self.patterns):
            raise ValueError(f"{self.name}: patterns must be unique")


@dataclass(frozen=True, slots=True)
class CategoryCountRule:
    """Require exact question-type counts across categories, optionally distinct."""

    name: str
    categories: tuple[str, ...]
    tossup_count: int
    bonus_count: int
    distinct_categories: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("category count rule name must be a non-empty string")
        if not self.categories or any(
            not isinstance(category, str) or not category
            for category in self.categories
        ):
            raise ValueError("category count rules require non-empty categories")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("category count rule categories must be unique")
        if not _nonnegative_int(self.tossup_count) or not _nonnegative_int(
            self.bonus_count
        ):
            raise ValueError("category count rule counts must be non-negative integers")
        if self.tossup_count + self.bonus_count == 0:
            raise ValueError("category count rules must require at least one question")
        if not isinstance(self.distinct_categories, bool):
            raise ValueError("distinct_categories must be a boolean")


@dataclass(frozen=True, slots=True)
class CategoryCountGroup:
    """A per-packet total drawn from one category group."""

    categories: tuple[str, ...]
    total_count: int
    minimum_per_type: int = 0
    minimum_per_category: int = 0
    maximum_per_category_per_type: int | None = None
    distinct_categories: bool = False

    def __post_init__(self) -> None:
        if not self.categories or any(
            not isinstance(category, str) or not category for category in self.categories
        ):
            raise ValueError("category count groups require non-empty categories")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("category count group categories must be unique")
        if not _nonnegative_int(self.total_count) or self.total_count == 0:
            raise ValueError("category count group total_count must be a positive integer")
        if not _nonnegative_int(self.minimum_per_type):
            raise ValueError("minimum_per_type must be a non-negative integer")
        if 2 * self.minimum_per_type > self.total_count:
            raise ValueError("minimum_per_type cannot exceed half of total_count")
        if not _nonnegative_int(self.minimum_per_category):
            raise ValueError("minimum_per_category must be a non-negative integer")
        if len(self.categories) * self.minimum_per_category > self.total_count:
            raise ValueError("category minimums cannot exceed total_count")
        if self.maximum_per_category_per_type is not None and (
            not _nonnegative_int(self.maximum_per_category_per_type)
            or self.maximum_per_category_per_type == 0
        ):
            raise ValueError("maximum_per_category_per_type must be a positive integer or None")
        if not isinstance(self.distinct_categories, bool):
            raise ValueError("distinct_categories must be a boolean")
        if self.distinct_categories and self.minimum_per_category > 1:
            raise ValueError(
                "distinct categories cannot satisfy minimum_per_category greater than 1"
            )
        if self.distinct_categories and self.total_count > len(self.categories):
            raise ValueError("distinct category group total cannot exceed its category count")


@dataclass(frozen=True, slots=True)
class CategoryGroupCountRule:
    """Per-packet type totals plus compact constraints over disjoint category groups."""

    name: str
    tossup_count: int
    bonus_count: int
    groups: tuple[CategoryCountGroup, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("category group count rule name must be a non-empty string")
        if not _nonnegative_int(self.tossup_count) or not _nonnegative_int(
            self.bonus_count
        ):
            raise ValueError("category group count rule counts must be non-negative integers")
        if not self.groups:
            raise ValueError("category group count rules require at least one group")
        if self.tossup_count + self.bonus_count != sum(
            group.total_count for group in self.groups
        ):
            raise ValueError("category group totals must equal the rule's tossup and bonus totals")
        minimum_tossups = sum(group.minimum_per_type for group in self.groups)
        maximum_tossups = sum(
            group.total_count - group.minimum_per_type for group in self.groups
        )
        if not minimum_tossups <= self.tossup_count <= maximum_tossups:
            raise ValueError("tossup_count is incompatible with group minimum_per_type constraints")
        categories = [category for group in self.groups for category in group.categories]
        if len(set(categories)) != len(categories):
            raise ValueError("category group categories must be disjoint")


@dataclass(frozen=True, slots=True)
class LeftoverBound:
    question_type: QuestionType
    minimum: int = 0
    maximum: int | None = None

    def __post_init__(self) -> None:
        if self.question_type not in QUESTION_TYPES:
            raise ValueError("leftover question_type must be 'tossup' or 'bonus'")
        _validate_bounds(self.minimum, self.maximum, "leftover bound")


@dataclass(frozen=True, slots=True)
class TossupBonusSeparation:
    """Within a packet, a tossup and a bonus sharing a category (and/or
    subcategory) must be more than ``window`` positions apart."""

    window: int
    by_category: bool = True
    by_subcategory: bool = False

    def __post_init__(self) -> None:
        if not _positive_int(self.window):
            raise ValueError("separation window must be a positive integer")
        if not (self.by_category or self.by_subcategory):
            raise ValueError("separation must apply to categories and/or subcategories")


@dataclass(frozen=True, slots=True)
class PacketBuildSpec:
    packet_count: int
    tossup_capacity: int
    bonus_capacity: int
    quotas: tuple[CategoryQuota, ...] = ()
    allowed_patterns: tuple[
        AllowedCountPatterns | CategoryCountRule | CategoryGroupCountRule, ...
    ] = ()
    aggregate_quotas: tuple[AggregateQuota, ...] = ()
    leftover_bounds: tuple[LeftoverBound, ...] = field(
        default_factory=lambda: (
            LeftoverBound("tossup"),
            LeftoverBound("bonus"),
        )
    )
    separation: TossupBonusSeparation | None = None

    def __post_init__(self) -> None:
        if not _positive_int(self.packet_count):
            raise ValueError("packet_count must be a positive integer")
        if not _nonnegative_int(self.tossup_capacity):
            raise ValueError("tossup_capacity must be a non-negative integer")
        if not _nonnegative_int(self.bonus_capacity):
            raise ValueError("bonus_capacity must be a non-negative integer")
        if len({rule.question_type for rule in self.leftover_bounds}) != len(
            self.leftover_bounds
        ):
            raise ValueError("leftover bounds may only be specified once per question type")
        if len({rule.selector for rule in self.aggregate_quotas}) != len(
            self.aggregate_quotas
        ):
            raise ValueError("aggregate quotas may only be specified once per selector")


def validate_distribution(
    spec: PacketBuildSpec,
    packets: Sequence[Mapping[CountSelector, int]],
    leftovers: Mapping[QuestionType, int],
) -> tuple[str, ...]:
    """Return hard-rule violations for a proposed packet distribution."""
    errors: list[str] = []
    if len(packets) != spec.packet_count:
        errors.append(
            f"expected {spec.packet_count} packets, received {len(packets)}"
        )
        return tuple(errors)

    for packet_index, counts in enumerate(packets, start=1):
        invalid_keys = [selector for selector in counts if selector.subcategory is None]
        if invalid_keys:
            errors.append(
                f"packet {packet_index}: counts must use exact category/subcategory keys"
            )
            continue
        if any(not _nonnegative_int(value) for value in counts.values()):
            errors.append(f"packet {packet_index}: counts must be non-negative integers")
            continue

        tossup_total = _count_type(counts, "tossup")
        bonus_total = _count_type(counts, "bonus")
        if tossup_total != spec.tossup_capacity:
            errors.append(
                f"packet {packet_index}: expected {spec.tossup_capacity} tossups, "
                f"received {tossup_total}"
            )
        if bonus_total != spec.bonus_capacity:
            errors.append(
                f"packet {packet_index}: expected {spec.bonus_capacity} bonuses, "
                f"received {bonus_total}"
            )

        for quota in spec.quotas:
            count = _count_selector(counts, quota.selector)
            if not _within_bounds(count, quota.minimum, quota.maximum):
                errors.append(
                    f"packet {packet_index}: {quota.selector} count {count} is outside "
                    f"{_bounds_text(quota.minimum, quota.maximum)}"
                )

        for rule in spec.allowed_patterns:
            if isinstance(rule, AllowedCountPatterns):
                actual = tuple(
                    _count_selector(counts, selector) for selector in rule.selectors
                )
                if actual not in rule.patterns:
                    errors.append(
                        f"packet {packet_index}: {rule.name} counts {actual} are not an allowed pattern"
                    )
            elif isinstance(rule, CategoryCountRule):
                category_counts = {
                    category: {
                        question_type: sum(
                            count
                            for selector, count in counts.items()
                            if selector.category == category
                            and selector.question_type == question_type
                        )
                        for question_type in QUESTION_TYPES
                    }
                    for category in rule.categories
                }
                tossup_total = sum(
                    values["tossup"] for values in category_counts.values()
                )
                bonus_total = sum(
                    values["bonus"] for values in category_counts.values()
                )
                is_distinct = not rule.distinct_categories or all(
                    values["tossup"] + values["bonus"] <= 1
                    for values in category_counts.values()
                )
                if (
                    tossup_total != rule.tossup_count
                    or bonus_total != rule.bonus_count
                    or not is_distinct
                ):
                    errors.append(
                        f"packet {packet_index}: {rule.name} requires "
                        f"{rule.tossup_count} tossups and {rule.bonus_count} bonuses"
                        + (
                            " from distinct categories"
                            if rule.distinct_categories
                            else ""
                        )
                    )

            else:
                rule_errors: list[str] = []
                for group in rule.groups:
                    group_counts = {
                        question_type: sum(
                            count
                            for selector, count in counts.items()
                            if selector.category in group.categories
                            and selector.question_type == question_type
                        )
                        for question_type in QUESTION_TYPES
                    }
                    group_total = sum(group_counts.values())
                    maximum_per_type = group.total_count - group.minimum_per_type
                    if (
                        group_total != group.total_count
                        or group_counts["tossup"] < group.minimum_per_type
                        or group_counts["bonus"] < group.minimum_per_type
                        or group_counts["tossup"] > maximum_per_type
                        or group_counts["bonus"] > maximum_per_type
                    ):
                        rule_errors.append(
                            f"group {group.categories} must contain {group.total_count} "
                            f"questions with at least {group.minimum_per_type} of each type"
                        )
                    for category in group.categories:
                        category_total = sum(
                            count
                            for selector, count in counts.items()
                            if selector.category == category
                        )
                        if category_total < group.minimum_per_category:
                            rule_errors.append(
                                f"group {group.categories} requires at least "
                                f"{group.minimum_per_category} from {category}"
                            )
                        if group.maximum_per_category_per_type is not None:
                            for question_type in QUESTION_TYPES:
                                category_type_count = sum(
                                    count
                                    for selector, count in counts.items()
                                    if selector.category == category
                                    and selector.question_type == question_type
                                )
                                if (
                                    category_type_count
                                    > group.maximum_per_category_per_type
                                ):
                                    rule_errors.append(
                                        f"group {group.categories} allows at most "
                                        f"{group.maximum_per_category_per_type} "
                                        f"{question_type} from {category}"
                                    )
                    if group.distinct_categories:
                        for category in group.categories:
                            category_total = sum(
                                count
                                for selector, count in counts.items()
                                if selector.category == category
                            )
                            if category_total > 1:
                                rule_errors.append(
                                    f"group {group.categories} requires distinct categories"
                                )
                                break
                group_tossups = sum(
                    sum(
                        count
                        for selector, count in counts.items()
                        if selector.category in group.categories
                        and selector.question_type == "tossup"
                    )
                    for group in rule.groups
                )
                group_bonuses = sum(
                    sum(
                        count
                        for selector, count in counts.items()
                        if selector.category in group.categories
                        and selector.question_type == "bonus"
                    )
                    for group in rule.groups
                )
                if (
                    group_tossups != rule.tossup_count
                    or group_bonuses != rule.bonus_count
                ):
                    rule_errors.append(
                        f"rule requires {rule.tossup_count} tossups and "
                        f"{rule.bonus_count} bonuses across its groups"
                    )
                errors.extend(
                    f"packet {packet_index}: {rule.name}: {error}"
                    for error in rule_errors
                )

    for quota in spec.aggregate_quotas:
        total = sum(_count_selector(counts, quota.selector) for counts in packets)
        if not _within_bounds(total, quota.minimum, quota.maximum):
            errors.append(
                f"set: {quota.selector} aggregate count {total} is outside "
                f"{_bounds_text(quota.minimum, quota.maximum)}"
            )

    for question_type in QUESTION_TYPES:
        count = leftovers.get(question_type)
        if count is None or not _nonnegative_int(count):
            errors.append(f"leftovers must include a non-negative {question_type} count")
            continue
        bound = next(
            (item for item in spec.leftover_bounds if item.question_type == question_type),
            LeftoverBound(question_type),
        )
        if not _within_bounds(count, bound.minimum, bound.maximum):
            errors.append(
                f"{question_type} leftovers {count} are outside "
                f"{_bounds_text(bound.minimum, bound.maximum)}"
            )
    return tuple(errors)


def _count_type(counts: Mapping[CountSelector, int], question_type: QuestionType) -> int:
    return sum(value for selector, value in counts.items() if selector.question_type == question_type)


def _count_selector(
    counts: Mapping[CountSelector, int], selector: CountSelector
) -> int:
    return sum(
        value
        for key, value in counts.items()
        if selector.matches(key)
    )


def _validate_bounds(minimum: int, maximum: int | None, label: str) -> None:
    if not _nonnegative_int(minimum):
        raise ValueError(f"{label} minimum must be a non-negative integer")
    if maximum is not None and not _nonnegative_int(maximum):
        raise ValueError(f"{label} maximum must be a non-negative integer or None")
    if maximum is not None and minimum > maximum:
        raise ValueError(f"{label} minimum cannot exceed maximum")


def _positive_int(value: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _within_bounds(value: int, minimum: int, maximum: int | None) -> bool:
    return value >= minimum and (maximum is None or value <= maximum)


def _bounds_text(minimum: int, maximum: int | None) -> str:
    return f"{minimum}..{maximum if maximum is not None else 'unbounded'}"

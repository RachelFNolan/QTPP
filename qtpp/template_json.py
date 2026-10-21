from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .build_spec import (
    AllowedCountPatterns,
    CategoryCountGroup,
    CategoryCountRule,
    CategoryGroupCountRule,
    CategoryQuota,
    CountSelector,
    LeftoverBound,
    TossupBonusSeparation,
)
from .templates import BuildTemplate

SCHEMA_VERSION = 1


def template_to_dict(template: BuildTemplate) -> dict[str, Any]:
    """Serialize a template to plain JSON-compatible data.

    Pattern counts are keyed by "type:category:subcategory" labels; zero counts are omitted.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "name": template.name,
        "tossup_capacity": template.tossup_capacity,
        "bonus_capacity": template.bonus_capacity,
        "quotas": [
            {
                "selector": _selector_to_dict(quota.selector),
                "minimum": quota.minimum,
                "maximum": quota.maximum,
            }
            for quota in template.quotas
        ],
        "allowed_patterns": [
            _rule_to_dict(rule)
            for rule in template.allowed_patterns
        ],
        "leftover_bounds": [
            {
                "question_type": bound.question_type,
                "minimum": bound.minimum,
                "maximum": bound.maximum,
            }
            for bound in template.leftover_bounds
        ],
        **(
            {
                "separation": {
                    "window": template.separation.window,
                    "by_category": template.separation.by_category,
                    "by_subcategory": template.separation.by_subcategory,
                }
            }
            if template.separation
            else {}
        ),
    }


def template_from_dict(data: dict[str, Any]) -> BuildTemplate:
    if not isinstance(data, dict):
        raise ValueError("template must be a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported template schema_version {version!r}; expected {SCHEMA_VERSION}")

    try:
        quotas = tuple(
            CategoryQuota(
                selector=_selector_from_dict(item["selector"]),
                minimum=item.get("minimum", 0),
                maximum=item.get("maximum"),
            )
            for item in data.get("quotas", [])
        )
        patterns = tuple(
            _pattern_rule_from_dict(item)
            for item in data.get("allowed_patterns", [])
        )
        leftovers = tuple(
            LeftoverBound(
                question_type=item["question_type"],
                minimum=item.get("minimum", 0),
                maximum=item.get("maximum"),
            )
            for item in data.get("leftover_bounds", [])
        )
        kwargs: dict[str, Any] = {"leftover_bounds": leftovers} if "leftover_bounds" in data else {}
        raw_separation = data.get("separation")
        if raw_separation is not None:
            kwargs["separation"] = TossupBonusSeparation(
                window=raw_separation["window"],
                by_category=raw_separation.get("by_category", True),
                by_subcategory=raw_separation.get("by_subcategory", False),
            )
        return BuildTemplate(
            name=data["name"],
            tossup_capacity=data["tossup_capacity"],
            bonus_capacity=data["bonus_capacity"],
            quotas=quotas,
            allowed_patterns=patterns,
            **kwargs,
        )
    except KeyError as error:
        raise ValueError(f"template is missing required field {error.args[0]!r}") from error
    except TypeError as error:
        raise ValueError(f"template has an invalid structure: {error}") from error


def save_template(template: BuildTemplate, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(template_to_dict(template), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_template(path: str | Path) -> BuildTemplate:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: invalid JSON: {error}") from error
    try:
        return template_from_dict(data)
    except ValueError as error:
        raise ValueError(f"{source}: {error}") from error


def _selector_to_dict(selector: CountSelector) -> dict[str, Any]:
    return {
        "question_type": selector.question_type,
        "category": selector.category,
        "subcategory": selector.subcategory,
    }


def _selector_from_dict(data: dict[str, Any]) -> CountSelector:
    return CountSelector(data["question_type"], data["category"], data.get("subcategory"))


def _selector_label(selector: CountSelector) -> str:
    parts = (selector.question_type, selector.category, selector.subcategory or "")
    if any(":" in part for part in parts):
        raise ValueError(f"selector {selector} contains ':' and cannot be used as a pattern label")
    return ":".join(parts)


def _rule_to_dict(
    rule: AllowedCountPatterns | CategoryCountRule | CategoryGroupCountRule,
) -> dict[str, Any]:
    if isinstance(rule, CategoryGroupCountRule):
        return {
            "name": rule.name,
            "counts": {
                "tossup": rule.tossup_count,
                "bonus": rule.bonus_count,
            },
            "groups": [
                {
                    "categories": list(group.categories),
                    "total": group.total_count,
                    "minimum_per_type": group.minimum_per_type,
                    "minimum_per_category": group.minimum_per_category,
                    "maximum_per_category_per_type": group.maximum_per_category_per_type,
                    "distinct_categories": group.distinct_categories,
                }
                for group in rule.groups
            ],
        }
    if isinstance(rule, CategoryCountRule):
        return {
            "name": rule.name,
            "categories": list(rule.categories),
            "counts": {
                "tossup": rule.tossup_count,
                "bonus": rule.bonus_count,
            },
            "distinct_categories": rule.distinct_categories,
        }
    return {
        "name": rule.name,
        "selectors": [_selector_to_dict(selector) for selector in rule.selectors],
        "patterns": [
            {
                _selector_label(selector): count
                for selector, count in zip(rule.selectors, pattern)
                if count
            }
            for pattern in rule.patterns
        ],
    }


def _pattern_rule_from_dict(
    data: dict[str, Any],
) -> AllowedCountPatterns | CategoryCountRule | CategoryGroupCountRule:
    if "groups" in data:
        counts = data["counts"]
        if not isinstance(counts, dict):
            raise ValueError(f"{data.get('name', 'category group count rule')}: counts must be an object")
        groups = data["groups"]
        if not isinstance(groups, list):
            raise ValueError(f"{data.get('name', 'category group count rule')}: groups must be an array")
        return CategoryGroupCountRule(
            name=data["name"],
            tossup_count=counts["tossup"],
            bonus_count=counts["bonus"],
            groups=tuple(
                CategoryCountGroup(
                    categories=tuple(group["categories"]),
                    total_count=group["total"],
                    minimum_per_type=group.get("minimum_per_type", 0),
                    minimum_per_category=group.get("minimum_per_category", 0),
                    maximum_per_category_per_type=group.get(
                        "maximum_per_category_per_type"
                    ),
                    distinct_categories=group.get("distinct_categories", False),
                )
                for group in groups
            ),
        )
    if "categories" in data or "counts" in data:
        counts = data["counts"]
        categories = data["categories"]
        if not isinstance(categories, list) or any(
            not isinstance(category, str) for category in categories
        ):
            raise ValueError(f"{data.get('name', 'category count rule')}: categories must be an array of strings")
        if not isinstance(counts, dict):
            raise ValueError(f"{data.get('name', 'category count rule')}: counts must be an object")
        return CategoryCountRule(
            name=data["name"],
            categories=tuple(categories),
            tossup_count=counts["tossup"],
            bonus_count=counts["bonus"],
            distinct_categories=data.get("distinct_categories", False),
        )
    selectors = tuple(_selector_from_dict(item) for item in data["selectors"])
    labels = {_selector_label(selector): index for index, selector in enumerate(selectors)}
    patterns = []
    for pattern in data["patterns"]:
        counts = [0] * len(selectors)
        for label, count in pattern.items():
            if label not in labels:
                raise ValueError(f"{data['name']}: pattern references unknown selector {label!r}")
            counts[labels[label]] = count
        patterns.append(tuple(counts))
    return AllowedCountPatterns(name=data["name"], selectors=selectors, patterns=tuple(patterns))

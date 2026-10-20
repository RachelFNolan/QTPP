"""Per-category taxonomy of alternate subcategories ("topic families").

JSON schema (also intended for a future GUI to edit):

    {"categories": {
        "Fine Arts": {
            "subcategories": ["Visual Fine Arts"],     # optional: only these primary subcategories
            "catch_all": ["Other", "Misc Arts"],        # never matched automatically
            "labels": {
                "Painting": {
                    "description": "paintings, painters, canvases",   # string or list of strings
                    "aliases": ["Paintings"],                          # existing pool values mapped here
                    "subcategories": ["Visual Fine Arts"]              # optional per-label restriction
                }
            }
        }
    }}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_TAXONOMY = Path(__file__).resolve().parent / "default_taxonomy.json"


def normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True, slots=True)
class LabelSpec:
    name: str
    descriptions: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    subcategories: frozenset[str] | None = None

    def allows(self, subcategory: str) -> bool:
        return self.subcategories is None or normalize(subcategory) in self.subcategories


@dataclass(frozen=True, slots=True)
class CategoryTaxonomy:
    name: str
    labels: tuple[LabelSpec, ...]
    catch_all: tuple[str, ...] = ()
    subcategories: frozenset[str] | None = None

    def allows(self, subcategory: str) -> bool:
        return self.subcategories is None or normalize(subcategory) in self.subcategories

    def canonical(self, value: str) -> str | None:
        """The label a pool value maps to (by name or alias), else None."""
        key = normalize(value)
        for label in self.labels:
            if key == normalize(label.name) or key in {normalize(a) for a in label.aliases}:
                return label.name
        return None


@dataclass(frozen=True, slots=True)
class Taxonomy:
    categories: Mapping[str, CategoryTaxonomy] = field(default_factory=dict)

    def category(self, name: str) -> CategoryTaxonomy | None:
        for key, value in self.categories.items():
            if normalize(key) == normalize(name):
                return value
        return None

    def alias_map(self) -> dict[str, str]:
        """Normalized alias or name -> canonical label, across all categories."""
        mapping: dict[str, str] = {}
        for category in self.categories.values():
            for label in category.labels:
                for alias in (label.name, *label.aliases):
                    mapping[normalize(alias)] = label.name
        return mapping

    def catch_alls(self) -> frozenset[str]:
        return frozenset(
            normalize(name) for category in self.categories.values() for name in category.catch_all
        )


def _strings(value: object, where: str) -> tuple[str, ...]:
    items = [value] if isinstance(value, str) else value
    if (
        not isinstance(items, list)
        or not items
        or any(not isinstance(item, str) or not item.strip() for item in items)
    ):
        raise ValueError(f"{where}: expected a non-empty string or list of strings")
    return tuple(items)


def _optional_set(value: object, where: str) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{where}: expected a list of strings")
    return frozenset(normalize(item) for item in value)


def taxonomy_from_dict(data: object, source: str = "taxonomy") -> Taxonomy:
    raw = data.get("categories") if isinstance(data, dict) else None
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f'{source}: expected {{"categories": {{name: {{...}}}}}}')
    categories: dict[str, CategoryTaxonomy] = {}
    for category_name, body in raw.items():
        where = f"{source}: category {category_name!r}"
        labels_raw = body.get("labels") if isinstance(body, dict) else None
        if not isinstance(labels_raw, dict) or not labels_raw:
            raise ValueError(f"{where}: needs a non-empty 'labels' object")
        labels = []
        for name, spec in labels_raw.items():
            if isinstance(spec, (str, list)):
                spec = {"description": spec}
            if not isinstance(spec, dict):
                raise ValueError(f"{where}: label {name!r} must be a description or object")
            aliases = spec.get("aliases", [])
            if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
                raise ValueError(f"{where}: label {name!r} aliases must be a list of strings")
            labels.append(
                LabelSpec(
                    name=name,
                    descriptions=_strings(spec.get("description", name), f"{where}: label {name!r}"),
                    aliases=tuple(aliases),
                    subcategories=_optional_set(
                        spec.get("subcategories"), f"{where}: label {name!r} subcategories"
                    ),
                )
            )
        catch_all = body.get("catch_all", [])
        if not isinstance(catch_all, list) or any(not isinstance(c, str) for c in catch_all):
            raise ValueError(f"{where}: catch_all must be a list of strings")
        categories[category_name] = CategoryTaxonomy(
            name=category_name,
            labels=tuple(labels),
            catch_all=tuple(catch_all),
            subcategories=_optional_set(body.get("subcategories"), f"{where}: subcategories"),
        )
    return Taxonomy(categories)


def load_taxonomy(path: str | Path = DEFAULT_TAXONOMY) -> Taxonomy:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: invalid JSON: {error}") from error
    return taxonomy_from_dict(data, str(source))


def label_texts(label: LabelSpec) -> list[str]:
    """Texts to embed for a label: its name prefixed to each description."""
    return [f"{label.name}. {text}" for text in label.descriptions]


def excluded_for(taxonomy: Taxonomy, extra: Iterable[str] = ()) -> frozenset[str]:
    return taxonomy.catch_alls() | {normalize(name) for name in extra}

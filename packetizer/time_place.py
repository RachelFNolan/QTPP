"""Detect an era and region for questions from their text.

Detection is a heuristic aid: results are meant to be written to a file,
reviewed, and passed to ``build_similarity(eras=..., regions=...)`` explicitly.
A question with no clear signal gets no tag and so is never penalized.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from .model import Bonus, QuestionSet, Tossup
from .similarity import question_text

# (label, exclusive upper-bound year); years are CE, negative for BCE.
ERAS: tuple[tuple[str, int], ...] = (
    ("Ancient (before 500)", 500),
    ("Medieval (500-1500)", 1500),
    ("Early modern (1500-1789)", 1789),
    ("Long 19th century (1789-1914)", 1914),
    ("World wars (1914-1945)", 1945),
    ("Postwar (1945 on)", 10_000),
)

_BCE_YEAR = re.compile(r"\b(\d{1,4})\s*(?:BCE|BC|B\.C\.E?\.)", re.IGNORECASE)
_CENTURY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)[- ]century(\s+(?:BCE|BC|B\.C\.))?", re.IGNORECASE)
_YEAR = re.compile(r"(?<![\d,.$])\b(1[0-9]{3}|20[0-2][0-9])\b(?![\d,%])")


def era_of(year: int) -> str:
    for label, upper in ERAS:
        if year < upper:
            return label
    return ERAS[-1][0]


def detect_era(text: str) -> str | None:
    """Era of the median year (or century) mentioned in text, or None."""
    years = [-int(match) for match in _BCE_YEAR.findall(text)]
    for number, bce in _CENTURY.findall(text):
        century = int(number)
        years.append(-century * 100 + 50 if bce else century * 100 - 50)
    years.extend(int(match) for match in _YEAR.findall(text))
    if not years:
        return None
    return era_of(int(statistics.median(years)))


REGIONS: dict[str, tuple[str, ...]] = {
    "Western Europe": (
        "France", "French", "Paris", "Britain", "British", "England", "English", "London", "Scotland",
        "Ireland", "Irish", "Spain", "Spanish", "Madrid", "Portugal", "Portuguese", "Italy", "Italian",
        "Rome", "Venice", "Florence", "Germany", "German", "Prussia", "Berlin", "Austria", "Netherlands",
        "Dutch", "Belgium", "Habsburg", "Napoleon", "Switzerland", "Scandinavia", "Sweden", "Norway",
        "Denmark",
    ),
    "Eastern Europe and Russia": (
        "Russia", "Russian", "Soviet", "USSR", "Moscow", "Poland", "Polish", "Ukraine", "Ukrainian",
        "Hungary", "Hungarian", "Czech", "Bohemia", "Romania", "Balkans", "Serbia", "Yugoslavia",
        "Bulgaria", "Byzantine", "Constantinople", "Lithuania",
    ),
    "Middle East and North Africa": (
        "Iran", "Persia", "Persian", "Iraq", "Mesopotamia", "Babylon", "Assyria", "Syria", "Egypt",
        "Egyptian", "Cairo", "Ottoman", "Turkey", "Turkish", "Arabia", "Arab", "Saudi", "Israel",
        "Palestine", "Jerusalem", "Lebanon", "Baghdad", "Abbasid", "Umayyad", "Morocco", "Algeria",
        "Libya", "Tunisia", "Yemen", "Mamluk", "Safavid",
    ),
    "Sub-Saharan Africa": (
        "Nigeria", "Ghana", "Mali", "Ethiopia", "Kenya", "Tanzania", "Congo", "Zimbabwe", "Zulu",
        "South Africa", "Sudan", "Senegal", "Uganda", "Angola", "Mozambique", "Songhai", "Benin",
        "Sahel", "Sokoto", "Rwanda", "Somalia", "Ashanti",
    ),
    "South Asia": (
        "India", "Indian", "Mughal", "Delhi", "Pakistan", "Bangladesh", "Bengal", "Sri Lanka", "Nepal",
        "Tibet", "Maurya", "Gupta", "Maratha", "Punjab", "Kashmir", "Mumbai", "Calcutta",
    ),
    "East Asia": (
        "China", "Chinese", "Beijing", "Han dynasty", "Tang dynasty", "Song dynasty", "Ming dynasty", "Qing", "Japan", "Japanese",
        "Tokyo", "Edo", "Meiji", "Korea", "Korean", "Taiwan", "Mongol", "Mongolia", "Manchu", "Shogun",
        "Kyoto",
    ),
    "Southeast Asia": (
        "Vietnam", "Vietnamese", "Thailand", "Siam", "Burma", "Myanmar", "Indonesia", "Java", "Malaysia",
        "Philippines", "Filipino", "Cambodia", "Khmer", "Laos", "Singapore", "Malay", "Sumatra",
    ),
    "North America": (
        "United States", "American", "America", "Texas",
        "California", "New York", "Canada", "Canadian", "Quebec", "Ontario", "Confederate", "Mississippi",
        "Cherokee", "Iroquois", "Virginia", "Massachusetts", "Chicago",
    ),
    "Latin America": (
        "Mexico", "Mexican", "Brazil", "Brazilian", "Argentina", "Chile", "Peru", "Inca", "Aztec",
        "Maya", "Colombia", "Venezuela", "Cuba", "Cuban", "Haiti", "Bolivia", "Caribbean", "Bolivar",
        "Guatemala", "Panama", "Jamaica",
    ),
    "Oceania and Central Asia": (
        "Australia", "Australian", "New Zealand", "Maori", "Polynesia", "Hawaii", "Pacific",
        "Uzbekistan", "Kazakhstan", "Samarkand", "Bukhara", "Afghanistan", "Turkmenistan", "Kyrgyz",
        "Silk Road", "Timur",
    ),
}

_REGION_PATTERNS = {
    region: re.compile(r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\b")
    for region, terms in REGIONS.items()
}


def detect_region(text: str) -> str | None:
    """Region with the most place-name hits, if it strictly beats every other region."""
    counts = Counter(
        {region: len(pattern.findall(text)) for region, pattern in _REGION_PATTERNS.items()}
    )
    ranked = counts.most_common(2)
    if not ranked or ranked[0][1] == 0:
        return None
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return None
    return ranked[0][0]


def _scoped(
    pool: QuestionSet, categories: Iterable[str] | None
) -> list[Tossup | Bonus]:
    allowed = {name.casefold() for name in categories} if categories else None
    return [
        question
        for question in (*pool.tossups, *pool.bonuses)
        if allowed is None or question.metadata.topic.category.casefold() in allowed
    ]


def detect_eras(pool: QuestionSet, categories: Iterable[str] | None = ("History", "Literature")) -> dict[str, str]:
    result = {}
    for question in _scoped(pool, categories):
        era = detect_era(question_text(question))
        if era:
            result[question.metadata.id] = era
    return result


def detect_regions(pool: QuestionSet, categories: Iterable[str] | None = ("History",)) -> dict[str, str]:
    result = {}
    for question in _scoped(pool, categories):
        region = detect_region(question_text(question))
        if region:
            result[question.metadata.id] = region
    return result


def save_time_place_tags(
    eras: Mapping[str, str], regions: Mapping[str, str], path: str | Path
) -> None:
    data = {
        "note": "Review and edit; delete entries you disagree with. Load with load_time_place_tags.",
        "eras": dict(eras),
        "regions": dict(regions),
    }
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_time_place_tags(path: str | Path) -> tuple[dict[str, str], dict[str, str]]:
    """Read {"eras": {id: era}, "regions": {id: region}} -> (eras, regions)."""
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: invalid JSON: {error}") from error
    result = []
    for key in ("eras", "regions"):
        tags = data.get(key, {}) if isinstance(data, dict) else None
        if not isinstance(tags, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items()
        ):
            raise ValueError(f"{source}: {key!r} must map question IDs to strings")
        result.append(dict(tags))
    return result[0], result[1]

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .model import (
    Bonus,
    BonusPart,
    Difficulty,
    QuestionMetadata,
    QuestionSet,
    QuestionSetMetadata,
    Tossup,
    Topic,
)


REQUIRED_COLUMNS = frozenset(
    {
        "question_id",
        "question_type",
        "set_id",
        "set_name",
        "set_year",
        "question_raw",
        "answer_raw",
        "category",
        "subcategory",
    }
)


def load_question_pool_csv(path: str | Path) -> QuestionSet:
    """Load a combined tossup/bonus CSV pool as an unpacketized question set."""
    source_path = Path(path)
    try:
        source_file = source_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as error:
        raise OSError(f"Unable to open question-pool CSV {source_path}: {error}") from error

    tossups: list[Tossup] = []
    bonuses: list[Bonus] = []
    question_ids: set[str] = set()
    set_identity: tuple[str, str, int] | None = None
    standard: bool | None = None
    difficulty: Difficulty | None = None
    known_standard_seen = False
    known_difficulty_seen = False

    with source_file:
        reader = csv.DictReader(source_file, strict=True)
        if reader.fieldnames is None:
            raise ValueError(f"{source_path}: CSV is missing its header row")
        if any(not name for name in reader.fieldnames):
            raise ValueError(f"{source_path}: CSV header contains an empty column name")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"{source_path}: CSV header contains duplicate column names")
        missing_columns = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
        if missing_columns:
            raise ValueError(
                f"{source_path}: CSV header is missing required columns: "
                + ", ".join(missing_columns)
            )

        try:
            for row_number, row in enumerate(reader, start=2):
                line_number = reader.line_num
                label = f"{source_path}: CSV row {row_number} (ending at line {line_number})"
                if None in row:
                    raise ValueError(f"{label}: record contains more fields than the header")
                if any(value is None for value in row.values()):
                    raise ValueError(f"{label}: record contains fewer fields than the header")

                row_set_identity = (
                    _required(row, "set_id", label),
                    _required(row, "set_name", label),
                    _integer(row, "set_year", label),
                )
                if set_identity is None:
                    set_identity = row_set_identity
                elif row_set_identity != set_identity:
                    raise ValueError(f"{label}: set ID, name, or year differs from other rows")

                row_standard = _optional_boolean(row.get("set_standard"), "set_standard", label)
                if row_standard is not None:
                    if known_standard_seen and standard != row_standard:
                        raise ValueError(f"{label}: set_standard differs from other rows")
                    standard = row_standard
                    known_standard_seen = True

                row_difficulty = _optional_difficulty(
                    row.get("set_difficulty"), "set_difficulty", label
                )
                if row_difficulty is not None:
                    if known_difficulty_seen and difficulty != row_difficulty:
                        raise ValueError(f"{label}: set_difficulty differs from other rows")
                    difficulty = row_difficulty
                    known_difficulty_seen = True

                question_id = _required(row, "question_id", label)
                if question_id in question_ids:
                    raise ValueError(f"{label}: duplicate question_id {question_id!r}")
                question_ids.add(question_id)

                question_type = _required(row, "question_type", label)
                metadata = QuestionMetadata(
                    id=question_id,
                    topic=Topic(
                        category=_required(row, "category", label),
                        subcategory=_required(row, "subcategory", label),
                        alternate_subcategory=_optional_text(row.get("alternate_subcategory")),
                    ),
                    difficulty=_question_difficulty(row.get("difficulty"), label),
                )
                question_raw = _required(row, "question_raw", label)
                answer_raw = _required(row, "answer_raw", label)
                question_sanitized = _optional_text(row.get("question_sanitized"))
                answer_sanitized = _optional_text(row.get("answer_sanitized"))

                if question_type == "tossup":
                    tossups.append(
                        Tossup(
                            metadata=metadata,
                            question=question_raw,
                            answer=answer_raw,
                            question_sanitized=question_sanitized,
                            answer_sanitized=answer_sanitized,
                        )
                    )
                elif question_type == "bonus":
                    bonuses.append(
                        _parse_bonus(
                            row,
                            metadata,
                            question_raw,
                            question_sanitized,
                            label,
                        )
                    )
                else:
                    raise ValueError(
                        f"{label}: question_type must be 'tossup' or 'bonus', "
                        f"not {question_type!r}"
                    )
        except csv.Error as error:
            raise ValueError(
                f"{source_path}: malformed CSV near line {reader.line_num}: {error}"
            ) from error

    if set_identity is None:
        raise ValueError(f"{source_path}: CSV contains no question rows")

    return QuestionSet(
        metadata=QuestionSetMetadata(
            id=set_identity[0],
            name=set_identity[1],
            year=set_identity[2],
            standard=standard,
            difficulty=difficulty,
        ),
        tossups=tuple(tossups),
        bonuses=tuple(bonuses),
    )


def _parse_bonus(
    row: dict[str, str],
    metadata: QuestionMetadata,
    question_raw: str,
    question_sanitized: str | None,
    label: str,
) -> Bonus:
    leadin = _required(row, "bonus_leadin_raw", label)
    parts_json = _required(row, "bonus_parts_json", label)
    try:
        parts_data = json.loads(parts_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label}: bonus_parts_json is invalid JSON: {error.msg}") from error
    if not isinstance(parts_data, list) or not parts_data:
        raise ValueError(f"{label}: bonus_parts_json must be a non-empty array")

    parts: list[BonusPart] = []
    for index, value in enumerate(parts_data):
        part_label = f"{label}: bonus_parts_json part {index + 1}"
        if not isinstance(value, dict):
            raise ValueError(f"{part_label} must be an object")
        parts.append(
            BonusPart(
                number=_object_integer(value, "part_number", part_label),
                question=_object_string(value, "question_raw", part_label),
                answer=_object_string(value, "answer_raw", part_label),
                value=_object_integer(value, "value", part_label),
                difficulty_modifier=_object_string(value, "difficulty_modifier", part_label),
                question_sanitized=_object_optional_string(
                    value, "question_sanitized", part_label
                ),
                answer_sanitized=_object_optional_string(
                    value, "answer_sanitized", part_label
                ),
            )
        )
    if len({part.number for part in parts}) != len(parts):
        raise ValueError(f"{label}: bonus part numbers must be unique")
    return Bonus(
        metadata=metadata,
        leadin=leadin,
        parts=tuple(parts),
        leadin_sanitized=_optional_text(row.get("bonus_leadin_sanitized")),
    )


def _required(row: dict[str, str], column: str, label: str) -> str:
    value = row.get(column)
    if value is None or not value.strip():
        raise ValueError(f"{label}: {column} must be non-empty")
    return value


def _optional_text(value: str | None) -> str | None:
    return value if value else None


def _integer(row: dict[str, str], column: str, label: str) -> int:
    value = _required(row, column, label)
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{label}: {column} must be an integer") from error


def _json_value(value: str | None, column: str, label: str) -> Any:
    if value is None or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label}: {column} is invalid JSON: {error.msg}") from error


def _optional_boolean(value: str | None, column: str, label: str) -> bool | None:
    parsed = _json_value(value, column, label)
    if parsed is None:
        return None
    if not isinstance(parsed, bool):
        raise ValueError(f"{label}: {column} must contain a JSON boolean or be blank")
    return parsed


def _optional_difficulty(
    value: str | None, column: str, label: str
) -> Difficulty | None:
    parsed = _json_value(value, column, label)
    if parsed is None:
        return None
    return _difficulty_from_value(parsed, f"{label}: {column}")


def _question_difficulty(value: str | None, label: str) -> Difficulty | None:
    parsed = _json_value(value, "difficulty", label)
    if parsed is None or (isinstance(parsed, int) and not isinstance(parsed, bool)):
        return None
    return _difficulty_from_value(parsed, f"{label}: difficulty")


def _difficulty_from_value(value: Any, label: str) -> Difficulty:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a difficulty object")
    level = value.get("level")
    sublevel = value.get("sublevel")
    if not isinstance(level, str) or not level:
        raise ValueError(f"{label}.level must be a non-empty string")
    if sublevel is not None and not (
        isinstance(sublevel, str)
        and bool(sublevel)
        or isinstance(sublevel, int)
        and not isinstance(sublevel, bool)
    ):
        raise ValueError(f"{label}.sublevel must be a non-empty string, integer, or null")
    return Difficulty(level=level, sublevel=sublevel)


def _object_string(value: dict[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return result


def _object_integer(value: dict[str, Any], key: str, label: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool):
        raise ValueError(f"{label}.{key} must be an integer")
    return result


def _object_optional_string(
    value: dict[str, Any], key: str, label: str
) -> str | None:
    result = value.get(key)
    if result is None or result == "":
        return None
    if not isinstance(result, str):
        raise ValueError(f"{label}.{key} must be a string or null")
    return result

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    Bonus,
    BonusPart,
    Difficulty,
    Packet,
    QuestionPlacement,
    QuestionMetadata,
    QuestionSet,
    QuestionSetMetadata,
    Tossup,
    Topic,
)


def load_question_set(directory: str | Path) -> QuestionSet:
    """Load packet JSON files from one directory into a normalized question set."""
    source_dir = Path(directory)
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Question-set directory does not exist: {source_dir}")

    paths = sorted(source_dir.glob("*.json"))
    if not paths:
        raise ValueError(f"No packet JSON files found in {source_dir}")

    parsed = [_load_packet_file(path) for path in paths]
    set_metadata = parsed[0][0]
    for path, (metadata, _, _, _) in zip(paths[1:], parsed[1:]):
        if metadata != set_metadata:
            raise ValueError(f"{path}: file belongs to a different question set")

    packets = tuple(sorted((packet for _, packet, _, _ in parsed), key=lambda packet: packet.number))
    tossups = tuple(question for _, _, packet_tossups, _ in parsed for question, _ in packet_tossups)
    bonuses = tuple(question for _, _, _, packet_bonuses in parsed for question, _ in packet_bonuses)
    return QuestionSet(metadata=set_metadata, tossups=tossups, bonuses=bonuses, packets=packets)


def _load_packet_file(
    path: Path,
) -> tuple[
    QuestionSetMetadata,
    Packet,
    tuple[tuple[Tossup, int], ...],
    tuple[tuple[Bonus, int], ...],
]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: invalid JSON: {error}") from error

    root = _mapping(data, str(path))
    tossup_rows = _list(root.get("tossups"), f"{path}: tossups")
    bonus_rows = _list(root.get("bonuses"), f"{path}: bonuses")
    rows = tossup_rows + bonus_rows
    if not rows:
        raise ValueError(f"{path}: packet contains no tossups or bonuses")

    first = _mapping(rows[0], f"{path}: question")
    packet_record = _mapping(first.get("packet"), f"{path}: question.packet")
    set_record = _mapping(first.get("set"), f"{path}: question.set")
    packet_metadata = _parse_packet_metadata(packet_record, path)
    set_metadata = _parse_set_metadata(set_record, path)

    tossups = tuple(sorted(
        (_parse_tossup(row, packet_metadata, set_metadata, path) for row in tossup_rows),
        key=lambda item: item[1],
    ))
    bonuses = tuple(sorted(
        (_parse_bonus(row, packet_metadata, set_metadata, path) for row in bonus_rows),
        key=lambda item: item[1],
    ))
    packet = Packet(
        id=packet_metadata[0],
        name=packet_metadata[1],
        number=packet_metadata[2],
        tossups=tuple(
            QuestionPlacement(question_id=question.metadata.id, number=number)
            for question, number in tossups
        ),
        bonuses=tuple(
            QuestionPlacement(question_id=question.metadata.id, number=number)
            for question, number in bonuses
        ),
    )
    return set_metadata, packet, tossups, bonuses


def _parse_tossup(
    value: Any,
    packet_metadata: tuple[str, str, int],
    set_metadata: QuestionSetMetadata,
    path: Path,
) -> tuple[Tossup, int]:
    row = _mapping(value, f"{path}: tossup")
    metadata, number = _parse_question_metadata(row, packet_metadata, set_metadata, path)
    tossup = Tossup(
        metadata=metadata,
        question=_string(row.get("question"), f"{path}: tossup.question"),
        answer=_string(row.get("answer"), f"{path}: tossup.answer"),
        question_sanitized=_optional_string(row.get("question_sanitized"), f"{path}: tossup.question_sanitized"),
        answer_sanitized=_optional_string(row.get("answer_sanitized"), f"{path}: tossup.answer_sanitized"),
    )
    return tossup, number


def _parse_bonus(
    value: Any,
    packet_metadata: tuple[str, str, int],
    set_metadata: QuestionSetMetadata,
    path: Path,
) -> tuple[Bonus, int]:
    row = _mapping(value, f"{path}: bonus")
    metadata, number = _parse_question_metadata(row, packet_metadata, set_metadata, path)
    leadin = _string(row.get("leadin"), f"{path}: bonus.leadin")
    questions = _list(row.get("parts"), f"{path}: bonus.parts")
    answers = _list(row.get("answers"), f"{path}: bonus.answers")
    values = _list(row.get("values"), f"{path}: bonus.values")
    modifiers = _list(row.get("difficultyModifiers"), f"{path}: bonus.difficultyModifiers")
    sanitized_questions = _optional_list(row.get("parts_sanitized"), f"{path}: bonus.parts_sanitized", len(questions))
    sanitized_answers = _optional_list(row.get("answers_sanitized"), f"{path}: bonus.answers_sanitized", len(questions))
    lengths = {len(questions), len(answers), len(values), len(modifiers)}
    if len(lengths) != 1 or not questions:
        raise ValueError(f"{path}: bonus parts, answers, values, and difficultyModifiers must have equal nonzero lengths")

    parts = tuple(
        BonusPart(
            number=index + 1,
            question=_string(question, f"{path}: bonus.parts[{index}]"),
            answer=_string(answer, f"{path}: bonus.answers[{index}]"),
            value=_integer(point_value, f"{path}: bonus.values[{index}]"),
            difficulty_modifier=_string(modifier, f"{path}: bonus.difficultyModifiers[{index}]"),
            question_sanitized=_optional_string(sanitized_questions[index], f"{path}: bonus.parts_sanitized[{index}]"),
            answer_sanitized=_optional_string(sanitized_answers[index], f"{path}: bonus.answers_sanitized[{index}]"),
        )
        for index, (question, answer, point_value, modifier) in enumerate(
            zip(questions, answers, values, modifiers)
        )
    )
    bonus = Bonus(
        metadata=metadata,
        leadin=leadin,
        parts=parts,
        leadin_sanitized=_optional_string(row.get("leadin_sanitized"), f"{path}: bonus.leadin_sanitized"),
    )
    return bonus, number


def _parse_question_metadata(
    row: dict[str, Any],
    packet_metadata: tuple[str, str, int],
    set_metadata: QuestionSetMetadata,
    path: Path,
) -> tuple[QuestionMetadata, int]:
    packet = _parse_packet_metadata(_mapping(row.get("packet"), f"{path}: question.packet"), path)
    question_set = _parse_set_metadata(_mapping(row.get("set"), f"{path}: question.set"), path)
    if packet != packet_metadata or question_set != set_metadata:
        raise ValueError(f"{path}: question metadata does not match the containing packet")

    alternate_subcategory = _optional_string(
        row.get("alternate_subcategory"), f"{path}: question.alternate_subcategory"
    )
    metadata = QuestionMetadata(
        id=_string(row.get("_id"), f"{path}: question._id"),
        topic=Topic(
            category=_string(row.get("category"), f"{path}: question.category"),
            subcategory=_string(row.get("subcategory"), f"{path}: question.subcategory"),
            alternate_subcategory=alternate_subcategory,
        ),
        difficulty=_parse_question_difficulty(row.get("difficulty"), path),
        author=_optional_string(row.get("author") or None, f"{path}: question.author"),
    )
    return metadata, _integer(row.get("number"), f"{path}: question.number")


def _parse_packet_metadata(value: dict[str, Any], path: Path) -> tuple[str, str, int]:
    return (
        _string(value.get("_id"), f"{path}: packet._id"),
        _string(value.get("name"), f"{path}: packet.name"),
        _integer(value.get("number"), f"{path}: packet.number"),
    )


def _parse_set_metadata(value: dict[str, Any], path: Path) -> QuestionSetMetadata:
    standard = value.get("standard")
    if standard is not None and not isinstance(standard, bool):
        raise ValueError(f"{path}: set.standard must be a boolean or null")
    difficulty = _parse_difficulty(value.get("difficulty"), f"{path}: set.difficulty")
    return QuestionSetMetadata(
        id=_string(value.get("_id"), f"{path}: set._id"),
        name=_string(value.get("name"), f"{path}: set.name"),
        year=_integer(value.get("year"), f"{path}: set.year"),
        standard=standard,
        difficulty=difficulty,
    )


def _parse_question_difficulty(value: Any, path: Path) -> Difficulty | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return None
    return _parse_difficulty(value, f"{path}: question.difficulty")


def _parse_difficulty(value: Any, label: str) -> Difficulty | None:
    if value is None:
        return None
    difficulty_record = _mapping(value, label)
    sublevel = difficulty_record.get("sublevel")
    if sublevel is not None and not (
        isinstance(sublevel, str) and sublevel
        or isinstance(sublevel, int) and not isinstance(sublevel, bool)
    ):
        raise ValueError(f"{label}.sublevel must be a non-empty string, integer, or null")
    return Difficulty(
        level=_string(difficulty_record.get("level"), f"{label}.level"),
        sublevel=sublevel,
    )


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _optional_list(value: Any, label: str, expected_length: int) -> list[Any]:
    if value is None:
        return [None] * expected_length
    rows = _list(value, label)
    if len(rows) != expected_length:
        raise ValueError(f"{label} must contain {expected_length} entries")
    return rows


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .json_import import (
    _list,
    _mapping,
    _parse_bonus,
    _parse_set_metadata,
    _parse_tossup,
)
from .model import QuestionSet

_POOL_PACKET = ("pool", "Question pool", 1)


def load_question_pool_json(path: str | Path) -> QuestionSet:
    """Load a JSON file of unpacketized tossups and bonuses as a question pool."""
    source_path = Path(path)
    try:
        text = source_path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise OSError(f"Unable to open question-pool JSON {source_path}: {error}") from error
    return parse_question_pool_json(text, source_path)


def parse_question_pool_json(text: str, path: str | Path = "question-pool.json") -> QuestionSet:
    """Parse pool JSON.

    Accepts either ``{"tossups": [...], "bonuses": [...], "set": {...}}`` or a bare
    list of questions, where bonuses are recognized by their ``leadin``/``parts`` fields.
    Questions need no packet or number; a set record is read from the top level or the
    first question and otherwise defaults from the file name.
    """
    label = Path(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label}: invalid JSON: {error}") from error

    top_set: Any = None
    if isinstance(data, list):
        rows = [_mapping(row, f"{label}: question[{index}]") for index, row in enumerate(data)]
        tossup_rows = [row for row in rows if not _is_bonus(row)]
        bonus_rows = [row for row in rows if _is_bonus(row)]
    else:
        root = _mapping(data, str(label))
        top_set = root.get("set")
        tossup_rows = _list(root.get("tossups", []), f"{label}: tossups")
        bonus_rows = _list(root.get("bonuses", []), f"{label}: bonuses")
    if not tossup_rows and not bonus_rows:
        raise ValueError(f"{label}: pool contains no tossups or bonuses")

    tossup_rows = [_mapping(row, f"{label}: tossup[{i}]") for i, row in enumerate(tossup_rows)]
    bonus_rows = [_mapping(row, f"{label}: bonus[{i}]") for i, row in enumerate(bonus_rows)]
    if top_set is None:
        top_set = next((row["set"] for row in tossup_rows + bonus_rows if row.get("set")), None)
    set_record = _set_record(top_set, label)
    set_metadata = _parse_set_metadata(set_record, label)

    tossups = tuple(
        _parse_tossup(_prepare(row, index, set_record), _POOL_PACKET, set_metadata, label)[0]
        for index, row in enumerate(tossup_rows)
    )
    bonuses = tuple(
        _parse_bonus(_prepare(row, index, set_record), _POOL_PACKET, set_metadata, label)[0]
        for index, row in enumerate(bonus_rows)
    )
    return QuestionSet(metadata=set_metadata, tossups=tossups, bonuses=bonuses)


def _is_bonus(row: dict[str, Any]) -> bool:
    return "leadin" in row or "parts" in row


def _set_record(value: Any, label: Path) -> dict[str, Any]:
    record = dict(_mapping(value, f"{label}: set")) if value is not None else {}
    stem = label.stem or "question-pool"
    record.setdefault("_id", stem)
    record.setdefault("name", stem)
    record.setdefault("year", date.today().year)
    return record


def _prepare(row: dict[str, Any], index: int, set_record: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(row)
    prepared["packet"] = {"_id": _POOL_PACKET[0], "name": _POOL_PACKET[1], "number": _POOL_PACKET[2]}
    prepared["set"] = set_record
    prepared.setdefault("number", index + 1)
    return prepared

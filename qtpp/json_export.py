from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .model import Bonus, Difficulty, Packet, QuestionSet, Tossup


def packet_filename(packet: Packet) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", packet.name).strip("-.") or "packet"
    return f"{packet.number:02d}_{slug}.json"


def packet_to_dict(question_set: QuestionSet, packet: Packet) -> dict[str, Any]:
    """Serialize one packet in the schema read by ``load_question_set``."""
    tossups = {question.metadata.id: question for question in question_set.tossups}
    bonuses = {question.metadata.id: question for question in question_set.bonuses}
    set_record = _set_record(question_set)
    packet_record = {"_id": packet.id, "name": packet.name, "number": packet.number}
    return {
        "tossups": [
            _tossup_record(tossups[item.question_id], item.number, packet_record, set_record)
            for item in packet.tossups
        ],
        "bonuses": [
            _bonus_record(bonuses[item.question_id], item.number, packet_record, set_record)
            for item in packet.bonuses
        ],
    }


def export_packets(question_set: QuestionSet, directory: str | Path) -> tuple[Path, ...]:
    """Write one JSON file per packet; nothing is written if any packet is invalid."""
    if not question_set.packets:
        raise ValueError("question set has no packets to export")
    documents = []
    for packet in question_set.packets:
        if not packet.tossups and not packet.bonuses:
            raise ValueError(f"packet {packet.number} is empty and cannot be exported")
        documents.append((packet_filename(packet), packet_to_dict(question_set, packet)))
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, document in documents:
        path = destination / filename
        path.write_text(
            json.dumps(document, indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        paths.append(path)
    return tuple(paths)


def _difficulty_record(difficulty: Difficulty | None) -> dict[str, Any] | None:
    if difficulty is None:
        return None
    return {"level": difficulty.level, "sublevel": difficulty.sublevel}


def _set_record(question_set: QuestionSet) -> dict[str, Any]:
    metadata = question_set.metadata
    record: dict[str, Any] = {
        "_id": metadata.id,
        "name": metadata.name,
        "year": metadata.year,
        "standard": metadata.standard,
    }
    if metadata.difficulty is not None:
        record["difficulty"] = _difficulty_record(metadata.difficulty)
    return record


def _common_record(
    question: Tossup | Bonus,
    number: int,
    packet_record: dict[str, Any],
    set_record: dict[str, Any],
) -> dict[str, Any]:
    metadata = question.metadata
    record: dict[str, Any] = {"_id": metadata.id}
    record.update(
        category=metadata.topic.category,
        subcategory=metadata.topic.subcategory,
    )
    if metadata.topic.alternate_subcategory is not None:
        record["alternate_subcategory"] = metadata.topic.alternate_subcategory
    record["number"] = number
    if metadata.difficulty is not None:
        record["difficulty"] = _difficulty_record(metadata.difficulty)
    record["packet"] = dict(packet_record)
    record["set"] = dict(set_record)
    return record


def _tossup_record(question: Tossup, number: int, packet_record, set_record) -> dict[str, Any]:
    record: dict[str, Any] = {"_id": question.metadata.id, "question": question.question}
    if question.question_sanitized is not None:
        record["question_sanitized"] = question.question_sanitized
    record["answer"] = question.answer
    if question.answer_sanitized is not None:
        record["answer_sanitized"] = question.answer_sanitized
    record.update(_common_record(question, number, packet_record, set_record))
    return record


def _bonus_record(question: Bonus, number: int, packet_record, set_record) -> dict[str, Any]:
    parts = sorted(question.parts, key=lambda part: part.number)
    record: dict[str, Any] = {"_id": question.metadata.id, "leadin": question.leadin}
    if question.leadin_sanitized is not None:
        record["leadin_sanitized"] = question.leadin_sanitized
    record["parts"] = [part.question for part in parts]
    if any(part.question_sanitized is not None for part in parts):
        record["parts_sanitized"] = [part.question_sanitized for part in parts]
    record["answers"] = [part.answer for part in parts]
    if any(part.answer_sanitized is not None for part in parts):
        record["answers_sanitized"] = [part.answer_sanitized for part in parts]
    record["values"] = [part.value for part in parts]
    record["difficultyModifiers"] = [part.difficulty_modifier for part in parts]
    record.update(_common_record(question, number, packet_record, set_record))
    return record

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from packetizer import Difficulty, load_question_set


COLUMNS = [
    "question_id",
    "question_type",
    "source_file",
    "set_id",
    "set_name",
    "set_year",
    "set_standard",
    "set_difficulty",
    "packet_id",
    "packet_name",
    "packet_number",
    "question_number",
    "question_raw",
    "question_sanitized",
    "answer_raw",
    "answer_sanitized",
    "category",
    "subcategory",
    "alternate_subcategory",
    "difficulty",
    "bonus_leadin_raw",
    "bonus_leadin_sanitized",
    "bonus_parts_json",
    "updated_at",
]


def generate_question_pool(source_dir: Path, output_path: Path) -> None:
    question_set = load_question_set(source_dir)
    source_by_packet: dict[str, str] = {}
    raw_by_id: dict[str, dict[str, dict]] = {"tossup": {}, "bonus": {}}

    for path in sorted(source_dir.glob("*.json")):
        source = json.loads(path.read_text(encoding="utf-8"))
        rows = source["tossups"] or source["bonuses"]
        packet_id = rows[0]["packet"]["_id"]
        source_by_packet[packet_id] = path.relative_to(source_dir.parent).as_posix()
        for record in source["tossups"]:
            raw_by_id["tossup"][record["_id"]] = record
        for record in source["bonuses"]:
            raw_by_id["bonus"][record["_id"]] = record

    tossups_by_id = {question.metadata.id: question for question in question_set.tossups}
    bonuses_by_id = {question.metadata.id: question for question in question_set.bonuses}
    rows = []
    metadata = question_set.metadata

    for packet in question_set.packets:
        for placement in packet.tossups:
            question = tossups_by_id[placement.question_id]
            raw = raw_by_id["tossup"][question.metadata.id]
            rows.append(
                {
                    "question_id": question.metadata.id,
                    "question_type": "tossup",
                    "source_file": source_by_packet[packet.id],
                    "set_id": metadata.id,
                    "set_name": metadata.name,
                    "set_year": metadata.year,
                    "set_standard": _json_value(metadata.standard),
                    "set_difficulty": _json_value(_difficulty_value(metadata.difficulty)),
                    "packet_id": packet.id,
                    "packet_name": packet.name,
                    "packet_number": packet.number,
                    "question_number": placement.number,
                    "question_raw": question.question,
                    "question_sanitized": question.question_sanitized or "",
                    "answer_raw": question.answer,
                    "answer_sanitized": question.answer_sanitized or "",
                    "category": question.metadata.topic.category,
                    "subcategory": question.metadata.topic.subcategory,
                    "alternate_subcategory": question.metadata.topic.alternate_subcategory or "",
                    "difficulty": _json_value(raw.get("difficulty")),
                    "bonus_leadin_raw": "",
                    "bonus_leadin_sanitized": "",
                    "bonus_parts_json": "",
                    "updated_at": raw.get("updatedAt", ""),
                }
            )

        for placement in packet.bonuses:
            question = bonuses_by_id[placement.question_id]
            raw = raw_by_id["bonus"][question.metadata.id]
            parts = [
                {
                    "part_number": part.number,
                    "question_raw": part.question,
                    "question_sanitized": part.question_sanitized,
                    "answer_raw": part.answer,
                    "answer_sanitized": part.answer_sanitized,
                    "value": part.value,
                    "difficulty_modifier": part.difficulty_modifier,
                }
                for part in question.parts
            ]
            rows.append(
                {
                    "question_id": question.metadata.id,
                    "question_type": "bonus",
                    "source_file": source_by_packet[packet.id],
                    "set_id": metadata.id,
                    "set_name": metadata.name,
                    "set_year": metadata.year,
                    "set_standard": _json_value(metadata.standard),
                    "set_difficulty": _json_value(_difficulty_value(metadata.difficulty)),
                    "packet_id": packet.id,
                    "packet_name": packet.name,
                    "packet_number": packet.number,
                    "question_number": placement.number,
                    "question_raw": question.leadin
                    + "\n"
                    + "\n".join(f"Part {part.number}: {part.question}" for part in question.parts),
                    "question_sanitized": (question.leadin_sanitized or "")
                    + "\n"
                    + "\n".join(
                        f"Part {part.number}: {part.question_sanitized or ''}"
                        for part in question.parts
                    ),
                    "answer_raw": "\n".join(
                        f"Part {part.number}: {part.answer}" for part in question.parts
                    ),
                    "answer_sanitized": "\n".join(
                        f"Part {part.number}: {part.answer_sanitized or ''}"
                        for part in question.parts
                    ),
                    "category": question.metadata.topic.category,
                    "subcategory": question.metadata.topic.subcategory,
                    "alternate_subcategory": question.metadata.topic.alternate_subcategory or "",
                    "difficulty": _json_value(raw.get("difficulty")),
                    "bonus_leadin_raw": question.leadin,
                    "bonus_leadin_sanitized": question.leadin_sanitized or "",
                    "bonus_parts_json": json.dumps(
                        parts, ensure_ascii=False, separators=(",", ":")
                    ),
                    "updated_at": raw.get("updatedAt", ""),
                }
            )

    rows.sort(
        key=lambda row: (
            row["packet_number"],
            row["question_type"] != "tossup",
            row["question_number"],
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} questions to {output_path}")


def _json_value(value: object) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _difficulty_value(value: Difficulty | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {"level": value.level, "sublevel": value.sublevel}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine packet JSON files into a CSV question pool."
    )
    parser.add_argument(
        "source_dir",
        type=Path,
        help="Directory containing packet JSON files",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="CSV output path (defaults to 'Question Pool.csv' in source_dir)",
    )
    args = parser.parse_args()
    source_dir = args.source_dir.resolve()
    output_path = args.output.resolve() if args.output else source_dir / "Question Pool.csv"
    generate_question_pool(source_dir, output_path)


if __name__ == "__main__":
    main()

"""User-selectable field mapping for question-pool CSV and JSON imports.

A mapping connects QTPP fields to the columns (CSV) or key paths (JSON, dotted for
nested keys such as ``packet.name``) of an arbitrary file. Mapped files are rewritten
into the canonical CSV/JSON shapes the existing importers read.
"""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping

SAMPLE_ROWS = 3
MAX_COLUMN_SCAN_ROWS = 500
MAX_SAMPLE_CHARS = 140
DEFAULT_MODIFIERS = ("e", "m", "h")
PART_VALUE = 10

# key, label, required, aliases (most preferred first)
FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "question", "label": "Tossup question text", "group": "Question",
     "aliases": ("question", "question_raw", "question_text", "tossup", "tossup_text", "text", "question_sanitized")},
    {"key": "answer", "label": "Tossup answer", "group": "Question",
     "aliases": ("answer", "answer_raw", "answerline", "answer_line", "answer_text", "answer_sanitized")},
    {"key": "category", "label": "Category", "group": "Classification", "required": True,
     "aliases": ("category", "cat", "topic")},
    {"key": "subcategory", "label": "Subcategory", "group": "Classification", "required": True,
     "aliases": ("subcategory", "sub_category", "subcat", "subject")},
    {"key": "alternate_subcategory", "label": "Alternate subcategory", "group": "Classification",
     "aliases": ("alternate_subcategory", "alt_subcategory", "alt_subcat", "alternate_subcat")},
    {"key": "author", "label": "Author", "group": "Details",
     "aliases": ("author", "authors", "writer", "written_by", "author_name", "packet_name", "packet")},
    {"key": "question_id", "label": "Question ID", "group": "Details",
     "aliases": ("question_id", "id", "_id", "qid", "uid")},
    {"key": "question_type", "label": "Question type (tossup/bonus)", "group": "Details",
     "aliases": ("question_type", "type", "kind", "tossup_or_bonus")},
    {"key": "set_name", "label": "Set name", "group": "Details",
     "aliases": ("set_name", "set", "tournament", "set_title")},
    {"key": "set_year", "label": "Set year", "group": "Details",
     "aliases": ("set_year", "year")},
    {"key": "question_sanitized", "label": "Tossup question (plain text)", "group": "Optional text",
     "aliases": ("question_sanitized", "question_plain")},
    {"key": "answer_sanitized", "label": "Tossup answer (plain text)", "group": "Optional text",
     "aliases": ("answer_sanitized", "answer_plain")},
    {"key": "bonus_leadin", "label": "Bonus lead-in", "group": "Bonus",
     "aliases": ("bonus_leadin_raw", "bonus_leadin", "leadin", "lead_in", "leadin_text", "intro", "leadin_sanitized")},
    {"key": "bonus_leadin_sanitized", "label": "Bonus lead-in (plain text)", "group": "Bonus",
     "aliases": ("bonus_leadin_sanitized", "leadin_sanitized")},
    {"key": "bonus_parts_list", "label": "Bonus parts (list field)", "group": "Bonus",
     "aliases": ("parts", "bonus_parts", "parts_sanitized")},
    {"key": "bonus_answers_list", "label": "Bonus answers (list field)", "group": "Bonus",
     "aliases": ("answers", "bonus_answers", "answers_sanitized")},
    {"key": "bonus_parts_json", "label": "Bonus parts (JSON objects)", "group": "Bonus",
     "aliases": ("bonus_parts_json", "parts_json")},
)
FIELD_KEYS = tuple(field["key"] for field in FIELDS)

_PART_QUESTION = re.compile(r"^(?:bonus_?)?(?:part|question|q|clue)_?(\d+)$")
_PART_ANSWER = re.compile(r"^(?:bonus_?)?(?:part_?)?(?:answer|ans|a)_?(\d+)$")


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def field_specs() -> list[dict[str, Any]]:
    return [
        {"key": f["key"], "label": f["label"], "group": f["group"], "required": bool(f.get("required"))}
        for f in FIELDS
    ]


def suggest_mapping(columns: list[str]) -> dict[str, Any]:
    """Suggest column choices; confidence is ``exact`` for known names, else ``guess``."""
    normalized = {column: _normalize(column) for column in columns}
    used: set[str] = set()
    mapping: dict[str, Any] = {key: None for key in FIELD_KEYS}
    confidence: dict[str, str] = {}

    questions: dict[int, str] = {}
    answers: dict[int, str] = {}
    for column, name in normalized.items():
        if match := _PART_ANSWER.match(name):
            answers.setdefault(int(match.group(1)), column)
        elif match := _PART_QUESTION.match(name):
            questions.setdefault(int(match.group(1)), column)
    pairs = [
        {"question": questions[number], "answer": answers.get(number)}
        for number in sorted(questions)
    ]
    if pairs:
        mapping["bonus_parts"] = pairs
        used.update(pair["question"] for pair in pairs)
        used.update(pair["answer"] for pair in pairs if pair["answer"])
        confidence["bonus_parts"] = "exact"
    else:
        mapping["bonus_parts"] = []

    for field in FIELDS:
        key = field["key"]
        for alias in field["aliases"]:
            column = next((c for c, n in normalized.items() if n == alias and c not in used), None)
            if column:
                mapping[key], confidence[key] = column, "exact"
                used.add(column)
                break
    for field in FIELDS:
        key = field["key"]
        if mapping[key]:
            continue
        candidates = {n: c for c, n in normalized.items() if c not in used}
        for alias in field["aliases"]:
            close = difflib.get_close_matches(alias, candidates, n=1, cutoff=0.75)
            if close:
                mapping[key], confidence[key] = candidates[close[0]], "guess"
                used.add(candidates[close[0]])
                break
    return {"mapping": mapping, "confidence": confidence}


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, dict):
                result.update(_flatten(item, path))
            else:
                result[path] = item
    return result


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_SAMPLE_CHARS:
        return value[: MAX_SAMPLE_CHARS - 1] + "…"
    if isinstance(value, (list, dict)):
        return _truncate(json.dumps(value, ensure_ascii=False))
    return value


def _csv_rows(text: str, label: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline=""))
    try:
        columns = reader.fieldnames
        if columns is None:
            raise ValueError(f"{label}: CSV is missing its header row")
        if any(not name for name in columns):
            raise ValueError(f"{label}: CSV header contains an empty column name")
        if len(columns) != len(set(columns)):
            raise ValueError(f"{label}: CSV header contains duplicate column names")
        rows = [{key: ("" if value is None else value) for key, value in row.items() if key is not None} for row in reader]
    except csv.Error as error:
        raise ValueError(f"{label}: malformed CSV: {error}") from error
    return list(columns), rows


def _json_rows(text: str, label: str) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any] | None]:
    """Return ``(kind, row)`` pairs (kind is "tossup", "bonus" or "") and the top-level set record."""
    try:
        data = json.loads(text.lstrip("\ufeff"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{label}: invalid JSON: {error}") from error
    top_set = None
    rows: list[tuple[str, dict[str, Any]]] = []
    if isinstance(data, list):
        groups = [("", data)]
    elif isinstance(data, dict):
        top_set = data.get("set") if isinstance(data.get("set"), dict) else None
        groups = [("tossup", data.get("tossups") or []), ("bonus", data.get("bonuses") or [])]
        if not any(group for _, group in groups) and all(isinstance(v, dict) for v in data.values()) and data:
            raise ValueError(f"{label}: expected a list of questions or tossups/bonuses lists")
    else:
        raise ValueError(f"{label}: expected a JSON object or array")
    for kind, group in groups:
        if not isinstance(group, list):
            raise ValueError(f"{label}: tossups and bonuses must be arrays")
        for index, row in enumerate(group):
            if not isinstance(row, dict):
                raise ValueError(f"{label}: question[{index}] must be an object")
            rows.append((kind, row))
    if not rows:
        raise ValueError(f"{label}: file contains no questions")
    return rows, top_set


def _looks_like_bonus(row: dict[str, Any], mapping: dict[str, Any]) -> bool:
    type_column = mapping.get("question_type")
    if type_column and _text(row.get(type_column)):
        try:
            return _normalize_type(_text(row.get(type_column)), "") == "bonus"
        except ValueError:
            pass
    bonus_columns = [mapping.get(k) for k in ("bonus_leadin", "bonus_parts_list", "bonus_parts_json")]
    bonus_columns += [pair["question"] for pair in mapping.get("bonus_parts", [])]
    return any(column and row.get(column) not in (None, "", []) for column in bonus_columns)


def _balanced_sample(rows: list[dict[str, Any]], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Up to SAMPLE_ROWS tossups followed by up to SAMPLE_ROWS bonuses."""
    tossups: list[dict[str, Any]] = []
    bonuses: list[dict[str, Any]] = []
    for row in rows:
        group = bonuses if _looks_like_bonus(row, mapping) else tossups
        if len(group) < SAMPLE_ROWS:
            group.append(row)
        if len(tossups) == SAMPLE_ROWS and len(bonuses) == SAMPLE_ROWS:
            break
    return tossups + bonuses


def inspect_csv(text: str, filename: str = "question-pool.csv") -> dict[str, Any]:
    columns, rows = _csv_rows(text, filename)
    if not rows:
        raise ValueError(f"{filename}: CSV contains no question rows")
    mapping = suggest_mapping(columns)["mapping"]
    return _inspection("csv", columns, _balanced_sample(rows, mapping), len(rows))


def inspect_json(text: str, filename: str = "question-pool.json") -> dict[str, Any]:
    rows, _ = _json_rows(text, filename)
    columns: list[str] = []
    seen: set[str] = set()
    flat_rows: list[dict[str, Any]] = []
    for _, row in rows:
        flat = _flatten(row)
        flat_rows.append(flat)
        if len(flat_rows) <= MAX_COLUMN_SCAN_ROWS:
            for path in flat:
                if path not in seen:
                    seen.add(path)
                    columns.append(path)
    mapping = suggest_mapping(columns)["mapping"]
    tossups = [flat for (kind, _), flat in zip(rows, flat_rows) if kind == "tossup"][:SAMPLE_ROWS]
    bonuses = [flat for (kind, _), flat in zip(rows, flat_rows) if kind == "bonus"][:SAMPLE_ROWS]
    if any(kind == "" for kind, _ in rows):
        untyped = [flat for (kind, _), flat in zip(rows, flat_rows) if kind == ""]
        sample = _balanced_sample(untyped, mapping)
    else:
        sample = tossups + bonuses
    return _inspection("json", columns, sample, len(rows))


def _inspection(kind: str, columns: list[str], sample: list[dict[str, Any]], row_count: int) -> dict[str, Any]:
    return {
        "kind": kind,
        "columns": columns,
        "sample": [{key: _truncate(value) for key, value in row.items()} for row in sample],
        "row_count": row_count,
        "suggestion": suggest_mapping(columns),
        "fields": field_specs(),
    }


def _clean_mapping(mapping: Any) -> dict[str, Any]:
    if not isinstance(mapping, Mapping):
        raise ValueError("mapping must be an object.")
    cleaned: dict[str, Any] = {}
    for key in FIELD_KEYS:
        value = mapping.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"mapping.{key} must be a column name or null.")
        cleaned[key] = value or None
    pairs = mapping.get("bonus_parts") or []
    if not isinstance(pairs, list):
        raise ValueError("mapping.bonus_parts must be a list.")
    cleaned["bonus_parts"] = []
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise ValueError("mapping.bonus_parts entries must be objects.")
        question, answer = pair.get("question"), pair.get("answer")
        if question or answer:
            cleaned["bonus_parts"].append({"question": question or None, "answer": answer or None})
    return cleaned


def _has_bonus_source(mapping: dict[str, Any]) -> bool:
    return bool(
        mapping["bonus_parts"]
        or mapping["bonus_parts_json"]
        or (mapping["bonus_parts_list"] and mapping["bonus_answers_list"])
    )


def _validate_mapping(mapping: dict[str, Any], columns: set[str] | None, label: str) -> None:
    missing = [f["label"] for f in FIELDS if f.get("required") and not mapping[f["key"]]]
    tossups = bool(mapping["question"] and mapping["answer"])
    bonuses = bool(mapping["bonus_leadin"] and _has_bonus_source(mapping))
    if not tossups and not bonuses:
        missing.append("Tossup question and answer, or bonus lead-in and parts")
    if missing:
        raise ValueError(f"{label}: choose a field for: " + "; ".join(missing))
    if columns is not None:
        used = [mapping[key] for key in FIELD_KEYS if mapping[key]]
        used += [value for pair in mapping["bonus_parts"] for value in pair.values() if value]
        unknown = sorted({name for name in used if name not in columns})
        if unknown:
            raise ValueError(f"{label}: mapped field(s) not found in the file: " + ", ".join(unknown))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return ""


def _as_list(value: Any, label: str) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{label}: expected a list but could not read it as JSON: {error.msg}") from error
    if not isinstance(value, list):
        raise ValueError(f"{label}: expected a list")
    return value


def _part_pairs(get, mapping: dict[str, Any], label: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for pair in mapping["bonus_parts"]:
        question = _text(get(pair["question"])) if pair["question"] else ""
        answer = _text(get(pair["answer"])) if pair["answer"] else ""
        if question or answer:
            pairs.append((question, answer))
    if pairs:
        return pairs
    if mapping["bonus_parts_json"]:
        items = _as_list(get(mapping["bonus_parts_json"]), f"{label}: {mapping['bonus_parts_json']}")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"{label}: each bonus part must be an object with a question and answer")
            question = item.get("question_raw", item.get("question", item.get("part")))
            answer = item.get("answer_raw", item.get("answer"))
            pairs.append((_text(question), _text(answer)))
        return pairs
    if mapping["bonus_parts_list"] and mapping["bonus_answers_list"]:
        questions = _as_list(get(mapping["bonus_parts_list"]), f"{label}: {mapping['bonus_parts_list']}")
        answers = _as_list(get(mapping["bonus_answers_list"]), f"{label}: {mapping['bonus_answers_list']}")
        if len(questions) != len(answers):
            raise ValueError(f"{label}: bonus has {len(questions)} parts but {len(answers)} answers")
        return [(_text(q), _text(a)) for q, a in zip(questions, answers)]
    return []


def _normalize_type(value: str, label: str) -> str:
    lowered = value.strip().lower().replace("-", "").replace(" ", "")
    if lowered in ("tossup", "tossups", "tu", "t", "toss"):
        return "tossup"
    if lowered in ("bonus", "bonuses", "b", "bo"):
        return "bonus"
    raise ValueError(f"{label}: question type {value!r} is not recognized (use tossup or bonus)")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "question-pool"


def _canonical_row(
    get, mapping: dict[str, Any], index: int, label: str, default_type: str, default_set: str
) -> dict[str, Any]:
    def scalar(key: str) -> str:
        return _text(get(mapping[key])) if mapping[key] else ""

    parts = _part_pairs(get, mapping, label) if _has_bonus_source(mapping) else []
    leadin = scalar("bonus_leadin")
    declared = scalar("question_type")
    if declared:
        kind = _normalize_type(declared, label)
    elif default_type:
        kind = default_type
    else:
        kind = "bonus" if (parts or leadin) and not scalar("question") else "tossup"

    row: dict[str, Any] = {
        "kind": kind,
        "id": scalar("question_id") or f"q{index + 1}",
        "category": scalar("category"),
        "subcategory": scalar("subcategory"),
        "alternate_subcategory": scalar("alternate_subcategory"),
        "author": scalar("author"),
        "set_name": scalar("set_name") or default_set,
        "set_year": scalar("set_year"),
    }
    for field in ("category", "subcategory"):
        if not row[field]:
            raise ValueError(f"{label}: {field} is empty")
    if kind == "tossup":
        row.update(
            question=scalar("question"),
            answer=scalar("answer"),
            question_sanitized=scalar("question_sanitized"),
            answer_sanitized=scalar("answer_sanitized"),
        )
        if not row["question"] or not row["answer"]:
            raise ValueError(f"{label}: tossup needs both a question and an answer")
    else:
        row.update(leadin=leadin, leadin_sanitized=scalar("bonus_leadin_sanitized"), parts=parts)
        if not leadin:
            raise ValueError(f"{label}: bonus lead-in is empty")
        if not parts or any(not q or not a for q, a in parts):
            raise ValueError(f"{label}: every bonus part needs a question and an answer")
    return row


def _modifier(index: int) -> str:
    return DEFAULT_MODIFIERS[index] if index < len(DEFAULT_MODIFIERS) else DEFAULT_MODIFIERS[-1]


def _set_year(value: str, label: str) -> int:
    if not value:
        return date.today().year
    try:
        return int(float(value))
    except ValueError as error:
        raise ValueError(f"{label}: set year {value!r} is not a number") from error


CANONICAL_CSV_COLUMNS = (
    "question_id", "question_type", "set_id", "set_name", "set_year", "question_raw", "answer_raw",
    "question_sanitized", "answer_sanitized", "category", "subcategory", "alternate_subcategory",
    "author", "bonus_leadin_raw", "bonus_leadin_sanitized", "bonus_parts_json",
)


def mapped_csv_text(text: str, mapping: Any, filename: str = "question-pool.csv") -> str:
    """Rewrite a CSV into the canonical pool-CSV layout using the user's field mapping."""
    columns, rows = _csv_rows(text, filename)
    mapping = _clean_mapping(mapping)
    _validate_mapping(mapping, set(columns), filename)
    if not rows:
        raise ValueError(f"{filename}: CSV contains no question rows")
    default_set = Path(filename).stem or "question-pool"
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CANONICAL_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for index, source in enumerate(rows):
        label = f"{filename}: CSV row {index + 2}"
        row = _canonical_row(source.get, mapping, index, label, "", default_set)
        out: dict[str, Any] = {
            "question_id": row["id"],
            "question_type": row["kind"],
            "set_id": _slug(row["set_name"]),
            "set_name": row["set_name"],
            "set_year": _set_year(row["set_year"], label),
            "category": row["category"],
            "subcategory": row["subcategory"],
            "alternate_subcategory": row["alternate_subcategory"],
            "author": row["author"],
        }
        if row["kind"] == "tossup":
            out.update(
                question_raw=row["question"], answer_raw=row["answer"],
                question_sanitized=row["question_sanitized"], answer_sanitized=row["answer_sanitized"],
            )
        else:
            out.update(
                question_raw=row["leadin"], answer_raw=row["parts"][0][1],
                bonus_leadin_raw=row["leadin"], bonus_leadin_sanitized=row["leadin_sanitized"],
                bonus_parts_json=json.dumps(
                    [
                        {
                            "part_number": number + 1,
                            "question_raw": question,
                            "answer_raw": answer,
                            "value": PART_VALUE,
                            "difficulty_modifier": _modifier(number),
                        }
                        for number, (question, answer) in enumerate(row["parts"])
                    ],
                    ensure_ascii=False,
                ),
            )
        writer.writerow(out)
    return output.getvalue()


def _lookup(row: dict[str, Any], path: str | None) -> Any:
    if not path:
        return None
    if path in row:
        return row[path]
    current: Any = row
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def mapped_pool_json(text: str, mapping: Any, filename: str = "question-pool.json") -> str:
    """Rewrite a JSON file into the canonical pool-JSON layout using the user's field mapping."""
    rows, top_set = _json_rows(text, filename)
    mapping = _clean_mapping(mapping)
    columns: set[str] = set()
    for _, row in rows[:MAX_COLUMN_SCAN_ROWS]:
        columns.update(_flatten(row))
    _validate_mapping(mapping, columns, filename)

    default_set = Path(filename).stem or "question-pool"
    tossups: list[dict[str, Any]] = []
    bonuses: list[dict[str, Any]] = []
    set_name = set_year = ""
    for index, (kind, source) in enumerate(rows):
        label = f"{filename}: question {index + 1}"
        row = _canonical_row(
            lambda path, source=source: _lookup(source, path), mapping, index, label, kind, default_set
        )
        set_name = set_name or (row["set_name"] if mapping["set_name"] else "")
        set_year = set_year or row["set_year"]
        out: dict[str, Any] = {
            "_id": row["id"],
            "category": row["category"],
            "subcategory": row["subcategory"],
            "alternate_subcategory": row["alternate_subcategory"] or None,
        }
        if row["author"]:
            out["author"] = row["author"]
        if row["kind"] == "tossup":
            out.update(question=row["question"], answer=row["answer"])
            if row["question_sanitized"]:
                out["question_sanitized"] = row["question_sanitized"]
            if row["answer_sanitized"]:
                out["answer_sanitized"] = row["answer_sanitized"]
            tossups.append(out)
        else:
            out.update(
                leadin=row["leadin"],
                parts=[q for q, _ in row["parts"]],
                answers=[a for _, a in row["parts"]],
                values=[PART_VALUE] * len(row["parts"]),
                difficultyModifiers=[_modifier(i) for i in range(len(row["parts"]))],
            )
            if row["leadin_sanitized"]:
                out["leadin_sanitized"] = row["leadin_sanitized"]
            bonuses.append(out)

    set_record = dict(top_set) if top_set else {}
    if set_name:
        set_record["name"] = set_name
        set_record.setdefault("_id", _slug(set_name))
    if set_year:
        set_record["year"] = _set_year(set_year, filename)
    payload: dict[str, Any] = {"tossups": tossups, "bonuses": bonuses}
    if set_record:
        payload["set"] = set_record
    return json.dumps(payload, ensure_ascii=False)

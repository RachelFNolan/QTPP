"""Append-only store of reviewer marks on possibly conflicting questions.

One JSON object per line, like the label store. A mark flags one question, may
link a second question, and may carry a short note. Edits, resolution and
removal are appended as newer records for the same mark id; the latest wins.
Question text is never stored.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MARKS = Path(__file__).resolve().parents[1] / "calibration" / "review_marks.jsonl"
STATUSES = ("open", "resolved", "removed")
MAX_NOTE = 500


def _write(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_mark(
    path: str | Path,
    *,
    question_id: str,
    other_id: str | None = None,
    note: str = "",
    pool: str = "",
    mark_id: str | None = None,
    status: str = "open",
    reviewer: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(STATUSES)}")
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise ValueError(f"note must be text of {MAX_NOTE} characters or fewer")
    if other_id is not None and other_id == question_id:
        raise ValueError("A mark cannot link a question to itself")
    now = _now()
    record = {
        "mark_id": mark_id or uuid.uuid4().hex[:12],
        "question_id": question_id,
        "other_id": other_id or None,
        "note": note.strip(),
        "status": status,
        "reviewer": reviewer.strip(),
        "pool": pool,
        "created_at": created_at or now,
        "updated_at": now,
    }
    return _write(Path(path), record)


def load_marks(path: str | Path) -> dict[str, dict[str, Any]]:
    """Latest record per mark id, including removed ones; malformed lines are skipped."""
    target = Path(path)
    latest: dict[str, dict[str, Any]] = {}
    if not target.exists():
        return latest
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(record, dict)
            and record.get("mark_id")
            and record.get("question_id")
            and record.get("status") in STATUSES
        ):
            latest[record["mark_id"]] = record
    return latest


def active_marks(path: str | Path, pool: str | None = None) -> list[dict[str, Any]]:
    """Non-removed marks, optionally restricted to one pool, oldest first."""
    records = [
        record
        for record in load_marks(path).values()
        if record["status"] != "removed" and (pool is None or record.get("pool", "") == pool)
    ]
    return sorted(records, key=lambda record: record.get("created_at", ""))

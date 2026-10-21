"""Append-only store of human similarity judgments for question pairs.

One JSON object per line keeps merges in version control simple. Pairs are keyed
by a hash of both questions' normalized text, so a label follows the content
rather than a pool-specific ID. Question text itself is never stored.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_LABELS = Path(__file__).resolve().parents[1] / "calibration" / "labels.jsonl"
LABELS = ("similar", "different", "borderline")
_SPACE = re.compile(r"\s+")


def _digest(text: str) -> str:
    return hashlib.sha1(_SPACE.sub(" ", text).strip().lower().encode("utf-8")).hexdigest()


def pair_key(first_text: str, second_text: str) -> str:
    """Order-independent key for a pair of question texts."""
    return hashlib.sha1("|".join(sorted((_digest(first_text), _digest(second_text)))).encode()).hexdigest()


def append_label(
    path: str | Path,
    *,
    key: str,
    first_id: str,
    second_id: str,
    label: str,
    reviewer: str = "",
    source: str = "web",
    pool: str = "",
    question_types: str = "",
) -> dict[str, Any]:
    if label not in LABELS:
        raise ValueError(f"label must be one of: {', '.join(LABELS)}")
    record = {
        "pair_key": key,
        "first_id": first_id,
        "second_id": second_id,
        "label": label,
        "reviewer": reviewer.strip(),
        "source": source,
        "pool": pool,
        "types": question_types,
        "labeled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_labels(path: str | Path) -> dict[str, dict[str, Any]]:
    """Latest label per pair key; malformed lines are skipped."""
    target = Path(path)
    latest: dict[str, dict[str, Any]] = {}
    if not target.exists():
        return latest
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("label") in LABELS and record.get("pair_key"):
            latest[record["pair_key"]] = record
    return latest


def label_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = {label: 0 for label in LABELS}
    for record in records:
        counts[record["label"]] += 1
    counts["total"] = sum(counts.values())
    return counts

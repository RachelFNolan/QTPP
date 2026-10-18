"""Export similarity pairs to a markdown review sheet and import the labels back.

Usage:
    python3 -m calibration.review_pairs export [--json JSON] [--markdown MD]
    python3 -m calibration.review_pairs import [--json JSON] [--markdown MD]

In the markdown, edit each pair's "Label:" line to one of: similar, different,
borderline. Import writes the labels to the JSON and marks it reviewed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "calibration" / "similarity_pairs.json"
DEFAULT_MARKDOWN = ROOT / "calibration" / "similarity_pairs_review.md"

_HEADING = re.compile(r"^## Pair (\d+) ", re.MULTILINE)
_LABEL = re.compile(r"^Label:\s*(\w*)", re.MULTILINE)


def label_word(pair: dict) -> str:
    if pair.get("borderline"):
        return "borderline"
    return "similar" if pair["label"] else "different"


def _block(text: str) -> str:
    """Blockquote with a blank quoted line between paragraphs so markdown keeps them separate."""
    return "\n>\n".join(f"> {line}" for line in text.split("\n"))


def export_markdown(data: dict) -> str:
    lines = [
        "# Similarity pair review",
        "",
        "For each pair, would a player notice a shared topic (same person, work, event or concept) "
        "if both questions were in the same packet? Edit each `Label:` line to "
        "`similar`, `different` or `borderline`. Pre-filled labels are heuristic guesses.",
        "",
    ]
    for number, pair in enumerate(data["pairs"], start=1):
        lines += [
            f"## Pair {number} ({pair['source']})",
            "",
            f"**A** ({pair['first_id'][-6:]})",
            "",
            _block(pair["first"]),
            "",
            f"**B** ({pair['second_id'][-6:]})",
            "",
            _block(pair["second"]),
            "",
            f"_Heuristic: {pair['heuristic_reason']}_",
            "",
            f"Label: {label_word(pair)}",
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def import_labels(data: dict, markdown: str) -> int:
    sections = _HEADING.split(markdown)[1:]
    labels = {int(sections[i]): sections[i + 1] for i in range(0, len(sections), 2)}
    if len(labels) != len(data["pairs"]):
        raise SystemExit(f"expected {len(data['pairs'])} pairs, found {len(labels)}")
    for number, pair in enumerate(data["pairs"], start=1):
        match = _LABEL.search(labels[number])
        word = match.group(1).lower() if match else ""
        if word not in {"similar", "different", "borderline"}:
            raise SystemExit(f"pair {number}: label must be similar, different or borderline")
        pair["borderline"] = word == "borderline"
        if word != "borderline":
            pair["label"] = word == "similar"
    data["reviewed"] = True
    return len(data["pairs"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export", "import"])
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()

    data = json.loads(args.json.read_text(encoding="utf-8"))
    if args.command == "export":
        args.markdown.write_text(export_markdown(data), encoding="utf-8")
        print(f"Wrote {len(data['pairs'])} pairs to {args.markdown}")
    else:
        count = import_labels(data, args.markdown.read_text(encoding="utf-8"))
        args.json.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Imported {count} labels into {args.json} (reviewed: true)")


if __name__ == "__main__":
    main()

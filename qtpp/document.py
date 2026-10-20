from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, Mapping

from .model import Bonus, Difficulty, Packet, QuestionSet, Tossup


@dataclass(frozen=True, slots=True)
class Run:
    """A span of text with uniform styling, ready for a DOCX or PDF writer."""

    text: str
    bold: bool = False
    underline: bool = False
    italic: bool = False


class _MarkupParser(HTMLParser):
    _STYLES = {"b": "bold", "strong": "bold", "u": "underline", "i": "italic", "em": "italic"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = {"bold": 0, "underline": 0, "italic": 0}
        self.runs: list[Run] = []

    def _emit(self, text: str) -> None:
        run = Run(
            text,
            self.depth["bold"] > 0,
            self.depth["underline"] > 0,
            self.depth["italic"] > 0,
        )
        if self.runs and _same_style(self.runs[-1], run):
            self.runs[-1] = Run(self.runs[-1].text + text, run.bold, run.underline, run.italic)
        else:
            self.runs.append(run)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._STYLES:
            self.depth[self._STYLES[tag]] += 1
        elif tag == "br":
            self._emit("\n")

    def handle_endtag(self, tag: str) -> None:
        style = self._STYLES.get(tag)
        if style and self.depth[style] > 0:
            self.depth[style] -= 1

    def handle_data(self, data: str) -> None:
        if data:
            self._emit(data)


def _same_style(first: Run, second: Run) -> bool:
    return (first.bold, first.underline, first.italic) == (
        second.bold,
        second.underline,
        second.italic,
    )


def parse_markup(text: str) -> tuple[Run, ...]:
    """Convert source HTML (b/strong, u, i/em, br) to styled runs; other tags are dropped."""
    parser = _MarkupParser()
    parser.feed(text)
    parser.close()
    return tuple(parser.runs)


def plain_text(runs: tuple[Run, ...]) -> str:
    return "".join(run.text for run in runs)


@dataclass(frozen=True, slots=True)
class FieldSelection:
    """Which fields appear in a rendered packet; serializable so a GUI can save presets."""

    text_form: Literal["raw", "sanitized"] = "raw"
    include_answers: bool = True
    bonus_values: bool = True
    bonus_modifiers: bool = True
    category_subcategory: bool = False
    alternate_subcategory: bool = False
    difficulty: bool = False
    source_question_id: bool = False
    author: bool = False
    front_set_name: bool = True
    front_packet_name: bool = True
    front_authors: bool = True

    def __post_init__(self) -> None:
        if self.text_form not in ("raw", "sanitized"):
            raise ValueError("text_form must be 'raw' or 'sanitized'")
        for item in fields(self):
            if item.name != "text_form" and not isinstance(getattr(self, item.name), bool):
                raise ValueError(f"{item.name} must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FieldSelection:
        if not isinstance(data, Mapping):
            raise ValueError("field selection must be a JSON object")
        unknown = sorted(set(data) - {item.name for item in fields(cls)})
        if unknown:
            raise ValueError(f"unknown field selection keys: {', '.join(unknown)}")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class FrontMatter:
    set_name: str | None = None
    set_year: int | None = None
    packet_name: str | None = None
    packet_number: int | None = None
    authors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DocTossup:
    number: int
    question: tuple[Run, ...]
    answer: tuple[Run, ...] | None
    details: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocBonusPart:
    number: int
    question: tuple[Run, ...]
    answer: tuple[Run, ...] | None
    value: int | None
    modifier: str | None


@dataclass(frozen=True, slots=True)
class DocBonus:
    number: int
    leadin: tuple[Run, ...]
    parts: tuple[DocBonusPart, ...]
    details: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PacketDocument:
    """Render-ready packet content containing only the selected fields."""

    front_matter: FrontMatter
    tossups: tuple[DocTossup, ...]
    bonuses: tuple[DocBonus, ...]


def load_authors(path: str | Path) -> dict[str, str]:
    """Load ``{"authors": {question_id: author}}`` for use as an author map."""
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: invalid JSON: {error}") from error
    authors = data.get("authors") if isinstance(data, dict) else None
    if not isinstance(authors, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in authors.items()
    ):
        raise ValueError(f'{source}: expected {{"authors": {{question_id: name}}}}')
    return authors


def build_packet_document(
    question_set: QuestionSet,
    packet: Packet,
    selection: FieldSelection = FieldSelection(),
    authors: Mapping[str, str] | None = None,
) -> PacketDocument:
    """Build one packet's document; ``authors`` maps question IDs to author names."""
    authors = authors or {}
    tossups = {question.metadata.id: question for question in question_set.tossups}
    bonuses = {question.metadata.id: question for question in question_set.bonuses}
    ordered = [*packet.tossups, *packet.bonuses]

    packet_authors: list[str] = []
    if selection.front_authors:
        for placement in ordered:
            name = authors.get(placement.question_id)
            if name and name not in packet_authors:
                packet_authors.append(name)

    metadata = question_set.metadata
    front = FrontMatter(
        set_name=metadata.name if selection.front_set_name else None,
        set_year=metadata.year if selection.front_set_name else None,
        packet_name=packet.name if selection.front_packet_name else None,
        packet_number=packet.number if selection.front_packet_name else None,
        authors=tuple(packet_authors),
    )
    return PacketDocument(
        front_matter=front,
        tossups=tuple(
            _doc_tossup(tossups[item.question_id], item.number, selection, authors, question_set)
            for item in packet.tossups
        ),
        bonuses=tuple(
            _doc_bonus(bonuses[item.question_id], item.number, selection, authors, question_set)
            for item in packet.bonuses
        ),
    )


def _runs(raw: str | None, sanitized: str | None, selection: FieldSelection) -> tuple[Run, ...]:
    if selection.text_form == "sanitized":
        if sanitized is not None:
            return (Run(sanitized),)
        return (Run(plain_text(parse_markup(raw or ""))),)
    return parse_markup(raw or "")


def _difficulty_label(difficulty: Difficulty | None) -> str | None:
    if difficulty is None:
        return None
    return difficulty.level if difficulty.sublevel is None else f"{difficulty.level} {difficulty.sublevel}"


def _details(
    question: Tossup | Bonus,
    selection: FieldSelection,
    authors: Mapping[str, str],
    question_set: QuestionSet,
) -> dict[str, str]:
    metadata = question.metadata
    details: dict[str, str] = {}
    if selection.category_subcategory:
        details["category"] = metadata.topic.category
        details["subcategory"] = metadata.topic.subcategory
    if selection.alternate_subcategory and metadata.topic.alternate_subcategory:
        details["alternate_subcategory"] = metadata.topic.alternate_subcategory
    if selection.difficulty:
        label = _difficulty_label(metadata.difficulty or question_set.metadata.difficulty)
        if label:
            details["difficulty"] = label
    if selection.source_question_id:
        details["source_question_id"] = metadata.id
    if selection.author and authors.get(metadata.id):
        details["author"] = authors[metadata.id]
    return details


def _doc_tossup(question, number, selection, authors, question_set) -> DocTossup:
    return DocTossup(
        number=number,
        question=_runs(question.question, question.question_sanitized, selection),
        answer=(
            _runs(question.answer, question.answer_sanitized, selection)
            if selection.include_answers
            else None
        ),
        details=_details(question, selection, authors, question_set),
    )


def _doc_bonus(question, number, selection, authors, question_set) -> DocBonus:
    parts = tuple(
        DocBonusPart(
            number=part.number,
            question=_runs(part.question, part.question_sanitized, selection),
            answer=(
                _runs(part.answer, part.answer_sanitized, selection)
                if selection.include_answers
                else None
            ),
            value=part.value if selection.bonus_values else None,
            modifier=part.difficulty_modifier if selection.bonus_modifiers else None,
        )
        for part in sorted(question.parts, key=lambda part: part.number)
    )
    return DocBonus(
        number=number,
        leadin=_runs(question.leadin, question.leadin_sanitized, selection),
        parts=parts,
        details=_details(question, selection, authors, question_set),
    )

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Topic:
    category: str
    subcategory: str
    alternate_subcategory: str | None = None


@dataclass(frozen=True, slots=True)
class Difficulty:
    level: str
    sublevel: int | str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.level, str) or not self.level:
            raise ValueError("Difficulty level must be a non-empty string")
        if isinstance(self.sublevel, bool) or (
            self.sublevel is not None
            and not isinstance(self.sublevel, (int, str))
        ):
            raise ValueError("Difficulty sublevel must be an integer, string, or None")
        if isinstance(self.sublevel, str) and not self.sublevel:
            raise ValueError("Difficulty sublevel must be a non-empty string")


@dataclass(frozen=True, slots=True)
class QuestionMetadata:
    """Question identity and classification; None difficulty inherits from its set."""

    id: str
    topic: Topic
    difficulty: Difficulty | None = None


@dataclass(frozen=True, slots=True)
class Tossup:
    metadata: QuestionMetadata
    question: str
    answer: str
    question_sanitized: str | None = None
    answer_sanitized: str | None = None


@dataclass(frozen=True, slots=True)
class BonusPart:
    number: int
    question: str
    answer: str
    value: int
    difficulty_modifier: str
    question_sanitized: str | None = None
    answer_sanitized: str | None = None


@dataclass(frozen=True, slots=True)
class Bonus:
    metadata: QuestionMetadata
    leadin: str
    parts: tuple[BonusPart, ...]
    leadin_sanitized: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionPlacement:
    question_id: str
    number: int


@dataclass(frozen=True, slots=True)
class Packet:
    id: str
    name: str
    number: int
    tossups: tuple[QuestionPlacement, ...]
    bonuses: tuple[QuestionPlacement, ...]


@dataclass(frozen=True, slots=True)
class QuestionSetMetadata:
    id: str
    name: str
    year: int
    standard: bool | None
    difficulty: Difficulty | None = None


@dataclass(frozen=True, slots=True)
class QuestionSet:
    metadata: QuestionSetMetadata
    tossups: tuple[Tossup, ...] = ()
    bonuses: tuple[Bonus, ...] = ()
    packets: tuple[Packet, ...] = ()

    def __post_init__(self) -> None:
        numbers = [packet.number for packet in self.packets]
        ids = [packet.id for packet in self.packets]
        if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
            raise ValueError("Question-set packets must have unique, ordered numbers")
        if len(ids) != len(set(ids)):
            raise ValueError("Question-set packet IDs must be unique")

        tossup_ids = [question.metadata.id for question in self.tossups]
        bonus_ids = [question.metadata.id for question in self.bonuses]
        if len(tossup_ids) != len(set(tossup_ids)):
            raise ValueError("Question-set tossup IDs must be unique")
        if len(bonus_ids) != len(set(bonus_ids)):
            raise ValueError("Question-set bonus IDs must be unique")
        if set(tossup_ids) & set(bonus_ids):
            raise ValueError("Question-set question IDs must be unique across tossups and bonuses")

        for label, question_type, packet_questions, pool_ids in (
            ("tossups", "tossup", (packet.tossups for packet in self.packets), set(tossup_ids)),
            ("bonuses", "bonus", (packet.bonuses for packet in self.packets), set(bonus_ids)),
        ):
            assigned_ids: set[str] = set()
            for placements in packet_questions:
                numbers = [placement.number for placement in placements]
                if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
                    raise ValueError(f"Packet {label} must have unique, ordered numbers")
                for placement in placements:
                    if placement.question_id not in pool_ids:
                        raise ValueError(f"Packet references an unknown {question_type} question")
                    if placement.question_id in assigned_ids:
                        raise ValueError(f"Question-set {label} may only be assigned to one packet")
                    assigned_ids.add(placement.question_id)

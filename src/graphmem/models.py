from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Strength(str, Enum):
    HARD = "hard"
    SOFT = "soft"


@dataclass
class Rule:
    id: str
    content: str
    strength: Strength = Strength.HARD
    scope: str = ""
    source_file: str = ""
    source_line: int = 0
    pattern: str = ""
    target_files: list[str] = field(default_factory=list)


@dataclass
class Action:
    type: str
    target: str
    agent: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    diff: str = ""


@dataclass
class Violation:
    rule: Rule
    action: Action
    confidence: float
    reason: str

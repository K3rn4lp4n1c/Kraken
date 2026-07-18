from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Challenge:
    id: str
    name: str
    description: str = ""
    points: int = 0
    category: str = "unknown"
    prerequisite: Challenge | None = None
    flag: str = ""

@dataclass
class Campaign:
    id: str
    name: str
    datetime: str
    url: str
    status: str
    challenges: list[Challenge]
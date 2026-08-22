from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class Paper:
    id: str
    title: str
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    published: str = ""
    updated: str = ""
    abstract: str = ""
    url: str = ""
    pdf_url: str = ""
    doi: str = ""
    source: str = ""
    content_type: str = "paper"
    company: str = ""
    venue: str = ""
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    score: int = 0
    summary: str = ""
    one_line_takeaway: str = ""
    core_method: str = ""
    innovation_points: list[str] = field(default_factory=list)
    experiment_results: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    practical_value: str = ""
    why_it_matters: str = ""
    evidence_basis: str = "metadata"
    analysis_status: str = ""
    analysis_signature: str = ""
    is_daily_pick: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Paper":
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

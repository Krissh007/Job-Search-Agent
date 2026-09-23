from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class Job:
    """
    Canonical job record passed between every pipeline stage:
    sources -> normalizer -> matcher -> database -> exports.
    """

    # Identity and card data
    title: str = ""
    company: str = ""
    location: str = ""
    job_url: str = ""
    source: str = ""

    salary: str = ""
    job_type: str = ""
    experience: str = ""
    experience_min: int | None = None
    experience_max: int | None = None

    # posted_date is the portal's raw text ("3 days ago"); posted_on is the
    # absolute ISO date derived from it at discovery time, so ages stay
    # correct on later days.
    posted_date: str = ""
    posted_days: int | None = None
    posted_on: str = ""

    description: str = ""
    card_description: str = ""

    search_term: str = ""
    search_location: str = ""
    discovered_at: str = ""

    # Matching output
    match_score: float | None = None
    match_category: str = ""
    match_reasons: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    eligible: bool = True
    rejection_reasons: list[str] = field(default_factory=list)
    evidence_count: int = 0

    # Tracking
    status: str = "new"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def field_names(cls) -> set[str]:
        return {item.name for item in fields(cls)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        """Build a Job from a dict, ignoring keys the model does not know."""
        names = cls.field_names()
        return cls(**{key: value for key, value in data.items() if key in names})

    def apply_match(self, match_result: dict[str, Any]) -> None:
        """Copy matcher output onto this job."""
        for key, value in match_result.items():
            if hasattr(self, key):
                setattr(self, key, value)

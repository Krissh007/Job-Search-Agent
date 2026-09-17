from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Job:
    """
    Standard job structure used by Indeed, LinkedIn, Naukri,
    matching, storage, and Excel export.
    """

    title: str = ""
    company: str = ""
    location: str = ""
    job_url: str = ""
    source: str = ""

    salary: str = ""
    posted_date: str = ""
    posted_days: int | None = None
    job_type: str = ""

    description: str = ""
    card_description: str = ""

    search_term: str = ""
    search_location: str = ""
    discovered_at: str = ""

    match_score: int = 0
    match_level: str = ""

    matching_roles: list[str] = field(default_factory=list)
    matching_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    matched_responsibilities: list[str] = field(default_factory=list)
    matched_tools: list[str] = field(default_factory=list)
    matched_industries: list[str] = field(default_factory=list)

    preferred_location_match: bool = False
    match_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the Job object into a dictionary.
        """
        return asdict(self)

    def apply_matching_result(
        self,
        matching_result: dict[str, Any],
    ) -> None:
        """
        Add matching results to this job.
        """
        for key, value in matching_result.items():
            if hasattr(self, key):
                setattr(self, key, value)
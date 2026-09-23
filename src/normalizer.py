from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

from src.freshness import derive_posted_on
from src.models import Job

# Alternative field names that different sources use for the same value.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "job_title", "position", "name"),
    "company": ("company", "company_name", "employer", "organization"),
    "location": ("location", "job_location", "city"),
    "job_url": ("job_url", "url", "link", "apply_url"),
    "source": ("source", "portal", "website"),
    "description": ("description", "job_description", "snippet", "summary"),
    "card_description": ("card_description",),
    "posted_date": ("posted_date", "date_posted", "posting_date"),
    "posted_days": ("posted_days", "posting_age_days"),
    "salary": ("salary", "salary_text", "compensation"),
    "job_type": ("job_type", "employment_type", "type"),
    "experience": ("experience", "experience_required", "years_of_experience"),
    "search_term": ("search_term", "search_keyword"),
    "search_location": ("search_location",),
    "discovered_at": ("discovered_at",),
}

# "3-5 Yrs", "3 - 5 years", "5+ years", "2 yrs"
EXPERIENCE_RANGE = re.compile(
    r"(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\s*(?:yrs?|years?)", re.IGNORECASE
)
EXPERIENCE_SINGLE = re.compile(r"(\d{1,2})\s*\+?\s*(?:yrs?|years?)", re.IGNORECASE)


def parse_experience_range(text: str) -> tuple[int | None, int | None]:
    """Parse portal experience text into (min, max) years."""
    value = str(text or "")
    match = EXPERIENCE_RANGE.search(value)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        return min(low, high), max(low, high)

    match = EXPERIENCE_SINGLE.search(value)
    if match:
        years = int(match.group(1))
        if "+" in value[match.start() : match.end()]:
            return years, None
        return years, years

    return None, None


class JobNormalizer:
    """Converts jobs collected from different sources into a common Job."""

    def normalize(
        self,
        job: Any,
        observed_on: date | None = None,
    ) -> Job:
        raw_job = self._convert_to_dictionary(job)

        values = {
            field_name: self._clean_text(self._first_value(raw_job, *aliases))
            for field_name, aliases in FIELD_ALIASES.items()
        }

        posted_days_text = values.pop("posted_days")
        normalized = Job(**values)
        normalized.posted_days = (
            int(posted_days_text) if posted_days_text.isdigit() else None
        )

        # Older sources put experience text ("3-5 Yrs") in job_type.
        if not normalized.experience and EXPERIENCE_RANGE.search(normalized.job_type):
            normalized.experience = normalized.job_type
            normalized.job_type = ""

        normalized.experience_min, normalized.experience_max = (
            parse_experience_range(normalized.experience)
        )

        today = observed_on or date.today()
        normalized.posted_on = self._clean_text(raw_job.get("posted_on")) or (
            derive_posted_on(normalized, today)
        )
        normalized.discovered_at = normalized.discovered_at or (
            datetime.now().isoformat(timespec="seconds")
        )
        normalized.source = normalized.source.lower()

        return normalized

    @staticmethod
    def _convert_to_dictionary(job: Any) -> dict[str, Any]:
        if job is None:
            return {}
        if isinstance(job, dict):
            return job.copy()
        if is_dataclass(job):
            return asdict(job)
        if hasattr(job, "__dict__"):
            return vars(job).copy()
        return {}

    @staticmethod
    def _first_value(data: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = data.get(key)
            if value is not None and value != "":
                return value
        return ""

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value)
        if isinstance(value, dict):
            return str(value)
        return " ".join(str(value).split()).strip()

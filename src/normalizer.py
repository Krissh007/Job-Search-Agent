from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict


class JobNormalizer:
    """
    Converts jobs collected from different sources into a common format.
    """

    def __init__(self, settings: Dict[str, Any] | None = None) -> None:
        self.settings = settings or {}

    def normalize(self, job: Any) -> Dict[str, Any]:
        """
        Normalize a job from:
        - a dictionary
        - a dataclass
        - an ordinary Python object
        """

        raw_job = self._convert_to_dictionary(job)

        title = self._first_value(
            raw_job,
            "title",
            "job_title",
            "position",
            "name",
        )

        company = self._first_value(
            raw_job,
            "company",
            "company_name",
            "employer",
            "organization",
        )

        location = self._first_value(
            raw_job,
            "location",
            "job_location",
            "city",
        )

        job_url = self._first_value(
            raw_job,
            "job_url",
            "url",
            "link",
            "apply_url",
        )

        source = self._first_value(
            raw_job,
            "source",
            "portal",
            "website",
        )

        description = self._first_value(
            raw_job,
            "description",
            "job_description",
            "snippet",
            "summary",
        )

        posted_date = self._first_value(
            raw_job,
            "posted_date",
            "date_posted",
            "posting_date",
        )

        posted_days = self._first_value(
            raw_job,
            "posted_days",
            "posting_age_days",
        )

        salary = self._first_value(
            raw_job,
            "salary",
            "salary_text",
            "compensation",
        )

        job_type = self._first_value(
            raw_job,
            "job_type",
            "employment_type",
            "type",
        )

        experience = self._first_value(
            raw_job,
            "experience",
            "experience_required",
            "years_of_experience",
            "job_type",
        )

        normalized_job = {
            "title": self._clean_text(title),
            "company": self._clean_text(company),
            "location": self._clean_text(location),
            "job_url": self._clean_text(job_url),
            "source": self._clean_text(source),
            "description": self._clean_text(description),
            "posted_date": self._clean_text(posted_date),
            "posted_days": self._clean_text(posted_days),
            "salary": self._clean_text(salary),
            "job_type": self._clean_text(job_type),
            "experience": self._clean_text(experience),
        }

        return normalized_job

    def normalize_job(self, job: Any) -> Dict[str, Any]:
        """
        Backward-compatible alias.
        """
        return self.normalize(job)

    @staticmethod
    def _convert_to_dictionary(job: Any) -> Dict[str, Any]:
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
    def _first_value(
        data: Dict[str, Any],
        *keys: str,
    ) -> Any:
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


if __name__ == "__main__":
    from src.sources.indeed_source import DiscoveredJob

    sample_job = DiscoveredJob(
        title="Business Analyst",
        company="Example Company",
        location="Hyderabad",
        job_url="https://example.com/job/123",
        source="Indeed",
        description="Business analysis role",
    )

    normalizer = JobNormalizer()
    normalized = normalizer.normalize(sample_job)

    print("Normalized job:")
    print(normalized)
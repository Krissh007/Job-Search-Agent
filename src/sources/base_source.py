from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.models import Job


class BaseJobSource(ABC):
    """
    Base interface that every job website source must follow.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ):
        self.config = config or {}

    @property
    @abstractmethod
    def source_name(self) -> str:
        """
        Return the source name, such as LinkedIn, Indeed, or Naukri.
        """
        raise NotImplementedError

    @abstractmethod
    def search_jobs(
        self,
        search_term: str,
        location: str,
        max_jobs: int = 50,
    ) -> list[Job]:
        """
        Search for jobs and return them as Job objects.
        """
        raise NotImplementedError

    def normalize_job(self, job: Job) -> Job:
        """
        Apply common cleanup to a job before returning it.
        """

        job.title = job.title.strip()
        job.company = job.company.strip()
        job.location = job.location.strip()
        job.job_url = job.job_url.strip()
        job.source = job.source.strip() or self.source_name

        return job
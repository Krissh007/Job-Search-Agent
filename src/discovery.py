from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page


@dataclass
class DiscoveredJob:
    title: str
    company: str
    location: str
    job_url: str
    source: str
    description: str = ""
    posted_date: Optional[str] = None


class JobDiscovery:
    """Collects job information from a job source."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def open_search_page(self, search_url: str) -> None:
        self.page.goto(search_url, wait_until="domcontentloaded")

    def discover_jobs(self) -> list[DiscoveredJob]:
        """
        Extract jobs from the currently opened page.

        This initial version uses a generic test-page structure.
        Real job-board selectors will be added separately.
        """
        jobs: list[DiscoveredJob] = []

        cards = self.page.locator(".job-card")

        for index in range(cards.count()):
            card = cards.nth(index)

            title = card.locator(".job-title").inner_text().strip()
            company = card.locator(".company").inner_text().strip()
            location = card.locator(".location").inner_text().strip()
            job_url = card.locator("a").get_attribute("href") or ""

            description_locator = card.locator(".job-description")

            if description_locator.count() > 0:
                description = (
                    description_locator.first.inner_text().strip()
                )
            else:
                description = ""

            jobs.append(
                DiscoveredJob(
                    title=title,
                    company=company,
                    location=location,
                    job_url=job_url,
                    source="test",
                    description=description,
                )
            )

        return jobs
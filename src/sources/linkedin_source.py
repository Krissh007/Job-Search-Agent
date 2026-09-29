from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Page

from src.models import Job
from src.sources.base_source import BaseJobSource


class LinkedInSource(BaseJobSource):
    """
    LinkedIn job discovery through the public (logged-out) job pages.

    No LinkedIn account is used, so there is no account to restrict. The
    search endpoint returns 10 job cards per request; the posting endpoint
    returns the full description and job criteria. Any non-200 response
    (429 rate limit, 999 bot check) stops this query instead of retrying.
    """

    SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    POSTING_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    VIEW_URL = "https://www.linkedin.com/jobs/view/{job_id}"
    PAGE_SIZE = 10

    def __init__(
        self,
        page: Page,
        enrich_details: bool = False,
        posted_within_days: int | None = 7,
        debug_directory: str = "data/debug",
        delay_ms: int = 2_000,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(config=config)
        self.page = page
        self.enrich_details = enrich_details
        self.posted_within_days = posted_within_days
        self.delay_ms = delay_ms
        self.debug_directory = Path(debug_directory)
        self.debug_directory.mkdir(parents=True, exist_ok=True)

    @property
    def source_name(self) -> str:
        return "linkedin"

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def search_jobs(
        self,
        search_term: str,
        location: str,
        max_jobs: int = 50,
        excluded_urls: set[str] | None = None,
        max_pages: int = 10,
    ) -> list[Job]:
        excluded_urls = excluded_urls or set()
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for page_number in range(max_pages):
            if len(jobs) >= max_jobs:
                break

            html = self._get(self.search_url(search_term, location, page_number * self.PAGE_SIZE))
            if html is None:
                break

            cards = self.parse_search_cards(html)
            print(f"LinkedIn page {page_number + 1}: {len(cards)} job cards found")
            if not cards:
                break

            for card in cards:
                if len(jobs) >= max_jobs:
                    break
                job_id = card.pop("job_id")
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                if card["job_url"] in excluded_urls:
                    print(f"Skipping existing LinkedIn job: {card['job_url']}")
                    continue

                job = Job(
                    **card,
                    source=self.source_name,
                    search_term=search_term,
                    search_location=location,
                )
                if self.enrich_details:
                    self.enrich_job_from_posting(job_id, job)

                jobs.append(self.normalize_job(job))
                print(f"Collected {len(jobs)}: {job.title} | {job.company} | {job.location}")

            if len(cards) < self.PAGE_SIZE:
                break

        print(f"LinkedIn jobs extracted: {len(jobs)}")
        return jobs

    # ------------------------------------------------------------------
    # URLs and requests
    # ------------------------------------------------------------------

    def search_url(self, keyword: str, location: str, start: int = 0) -> str:
        if "india" not in location.lower():
            location = f"{location}, India"
        params: dict[str, Any] = {"keywords": keyword, "location": location, "start": start}
        if self.posted_within_days:
            # f_TPR limits results to postings from the last N seconds.
            params["f_TPR"] = f"r{int(self.posted_within_days) * 86_400}"
        return f"{self.SEARCH_URL}?{urlencode(params)}"

    # Seconds to wait before retrying a rate-limited (429) request.
    RATE_LIMIT_BACKOFF_MS = (20_000, 60_000)

    def _get(self, url: str) -> str | None:
        self.page.wait_for_timeout(self.delay_ms)
        response = self._request(url)
        for backoff_ms in self.RATE_LIMIT_BACKOFF_MS:
            if response is None or response.status != 429:
                break
            print(f"LinkedIn rate limit (429); waiting {backoff_ms // 1000}s before retrying.")
            self.page.wait_for_timeout(backoff_ms)
            response = self._request(url)

        if response is None:
            return None
        if response.status != 200:
            print(
                f"LinkedIn returned HTTP {response.status}; stopping this query. "
                "(429 = rate limited, 999 = bot check.)"
            )
            self._save_debug(f"linkedin_http_{response.status}.html", response.text())
            return None
        return response.text()

    def _request(self, url: str) -> Any:
        try:
            return self.page.request.get(url, timeout=30_000)
        except Exception as exc:
            print(f"LinkedIn request failed: {exc}")
            return None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_search_cards(self, html: str) -> list[dict[str, Any]]:
        self.page.set_content(html)
        cards: list[dict[str, Any]] = []

        for card in self.page.locator("div.base-search-card").all():
            job_id = self._job_id(card)
            title = self._text(card, "h3.base-search-card__title")
            if not job_id or not title:
                continue

            cards.append(
                {
                    "job_id": job_id,
                    "job_url": self.VIEW_URL.format(job_id=job_id),
                    "title": title,
                    "company": self._text(card, "h4.base-search-card__subtitle"),
                    "location": self._text(card, "span.job-search-card__location"),
                    "salary": self._text(card, "span.job-search-card__salary-info"),
                    # An absolute date, so freshness never depends on "N days ago".
                    "posted_date": self._attribute(card, "time", "datetime"),
                }
            )
        return cards

    def enrich_job_from_posting(self, job_id: str, job: Job) -> None:
        html = self._get(self.POSTING_URL.format(job_id=job_id))
        if html is None:
            return

        self.page.set_content(html)
        description = self._text(self.page, "div.show-more-less-html__markup", multiline=True)
        if description:
            job.card_description = job.description
            job.description = description[:20_000]

        criteria = {}
        for item in self.page.locator("li.description__job-criteria-item").all():
            label = self._text(item, "h3")
            value = self._text(item, "span")
            if label and value:
                criteria[label.lower()] = value

        job.job_type = " · ".join(
            value
            for value in (criteria.get("seniority level"), criteria.get("employment type"))
            if value
        )

    @staticmethod
    def _job_id(card: Any) -> str:
        urn = card.get_attribute("data-entity-urn") or ""
        match = re.search(r"(\d{6,})$", urn)
        if match:
            return match.group(1)

        link = card.locator("a.base-card__full-link").first
        href = link.get_attribute("href") if link.count() else ""
        match = re.search(r"-(\d{6,})(?:\?|$)", href or "")
        return match.group(1) if match else ""

    @staticmethod
    def _text(scope: Any, selector: str, multiline: bool = False) -> str:
        locator = scope.locator(selector).first
        if locator.count() == 0:
            return ""
        text = locator.inner_text().replace("\xa0", " ")
        if multiline:
            lines = [" ".join(line.split()) for line in text.splitlines()]
            return "\n".join(line for line in lines if line)
        return " ".join(text.split())

    @staticmethod
    def _attribute(scope: Any, selector: str, name: str) -> str:
        locator = scope.locator(selector).first
        if locator.count() == 0:
            return ""
        return (locator.get_attribute(name) or "").strip()

    def _save_debug(self, filename: str, html: str) -> None:
        try:
            (self.debug_directory / filename).write_text(html, encoding="utf-8")
        except OSError:
            pass

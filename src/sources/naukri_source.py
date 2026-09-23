from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from src.models import Job
from src.sources.base_source import BaseJobSource


class NaukriSource(BaseJobSource):
    """
    Naukri job discovery source.

    This source:
    - Uses the shared Job model.
    - Implements the shared BaseJobSource interface.
    - Does not bypass CAPTCHA or login verification.
    - Saves debug HTML when access fails.
    """

    BASE_URL = "https://www.naukri.com"

    def __init__(
        self,
        page: Page,
        keyword: str = "",
        location: str = "",
        debug_directory: str = "data/debug",
        config: dict[str, Any] | None = None,
        enrich_details: bool = False,
    ) -> None:
        super().__init__(config=config)

        self.page = page
        self.keyword = keyword
        self.location = location
        # When True, open each job's detail page to fetch the full description.
        # This is slow (1 extra page load per job) so it defaults to False.
        self.enrich_details = enrich_details

        self.debug_directory = Path(debug_directory)
        self.debug_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.search_url = self.build_search_url(
            keyword=keyword,
            location=location,
        )

    @property
    def source_name(self) -> str:
        return "naukri"

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def search_jobs(
        self,
        search_term: str,
        location: str,
        max_jobs: int = 20,
        excluded_urls: set[str] | None = None,
        max_pages: int = 10,
    ) -> list[Job]:
        """
        Search Naukri and return shared Job objects.
        """

        self.keyword = search_term
        self.location = location
        self.search_url = self.build_search_url(
            keyword=search_term,
            location=location,
        )

        return self.discover_jobs(
            max_jobs=max_jobs,
            excluded_urls=excluded_urls,
            max_pages=max_pages,
        )

    def discover_jobs(
        self,
        max_jobs: int = 20,
        excluded_urls: set[str] | None = None,
        max_pages: int = 10,
    ) -> list[Job]:
        print("Opening Naukri search page...")
        print(f"URL: {self.search_url}")

        try:
            self.page.goto(
                self.search_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )

        except PlaywrightTimeoutError:
            print(
                "Naukri search page navigation timed out. "
                "Continuing..."
            )

        except Exception as exc:
            print(
                f"Could not open Naukri search page: {exc}"
            )

            self.save_debug_html(
                "naukri_navigation_error.html"
            )
            return []

        self.page.wait_for_timeout(3_000)

        if self.is_blocked_or_login_page():
            print(
                "Naukri appears to require login, verification, "
                "or additional access."
            )

            self.save_debug_html(
                "naukri_blocked_debug.html"
            )
            return []

        first_cards = self.find_job_cards()
        if first_cards.count() == 0:
            self.save_debug_html(
                "naukri_search_debug.html"
            )
            return []

        jobs: list[Job] = []
        seen_urls: set[str] = set()
        excluded_urls = excluded_urls or set()
        detail_page = None
        if self.enrich_details:
            try:
                detail_page = self.page.context.new_page()
            except Exception:
                detail_page = None

        page_number = 1
        while len(jobs) < max_jobs and page_number <= max_pages:
            cards = self.find_job_cards()
            card_count = cards.count()
            print(
                f"Naukri page {page_number}: "
                f"{card_count} job cards found"
            )

            for index in range(card_count):
                if len(jobs) >= max_jobs:
                    break

                card = cards.nth(index)

                try:
                    title = self.extract_text(
                        card,
                        [
                            "a.title",
                            "a[class*='title']",
                            "[class*='jobTitle']",
                            "h2",
                        ],
                    )

                    company = self.extract_text(
                        card,
                        [
                            "a.comp-name",
                            "a[class*='comp']",
                            "[class*='company']",
                        ],
                    )

                    location = self.extract_text(
                        card,
                        [
                            "span.locWdth",
                            "[class*='location']",
                            "[class*='loc']",
                        ],
                    )

                    salary = self.extract_text(
                        card,
                        [
                            "span.sal",
                            "[class*='salary']",
                        ],
                    )

                    experience = self.extract_text(
                        card,
                        [
                            "span.expwdth",
                            "[class*='experience']",
                            "[class*='exp']",
                        ],
                    )

                    description = self.extract_text(
                        card,
                        [
                            "div.job-desc",
                            "[class*='job-desc']",
                            "[class*='description']",
                        ],
                    )

                    posted_date = self.extract_posted_date(card)

                    job_url = self.extract_url(
                        card,
                        [
                            "a.title",
                            "a[class*='title']",
                            "a[href*='/job-listings-']",
                        ],
                    )

                    if not title or not job_url:
                        print(
                            f"Skipping Naukri card {index + 1}: "
                            "missing title or job URL"
                        )
                        continue

                    if job_url in seen_urls:
                        print(
                            f"Skipping duplicate Naukri job: "
                            f"{job_url}"
                        )
                        continue

                    if job_url in excluded_urls:
                        print(
                            f"Skipping existing Naukri job: {job_url}"
                        )
                        seen_urls.add(job_url)
                        continue

                    seen_urls.add(job_url)

                    job = Job(
                        title=title,
                        company=company,
                        location=location,
                        job_url=job_url,
                        source=self.source_name,
                        description=description,
                        card_description=description,
                        posted_date=posted_date,
                        posted_days=self.extract_posted_days(posted_date),
                        salary=salary,
                        experience=experience,
                        search_term=self.keyword,
                        search_location=self.location,
                    )

                    if detail_page is not None:
                        self.enrich_job_from_detail(detail_page, job)

                    job = self.normalize_job(job)
                    jobs.append(job)

                    print(
                        f"Collected {len(jobs)}: "
                        f"{job.title} | "
                        f"{job.company} | "
                        f"{job.location}"
                    )

                except Exception as exc:
                    print(
                        f"Could not read Naukri card "
                        f"{index + 1}: {exc}"
                    )

            if len(jobs) >= max_jobs:
                break
            if not self.click_next_page():
                break
            page_number += 1

        if detail_page is not None:
            try:
                detail_page.close()
            except Exception:
                pass

        print(f"Naukri jobs extracted: {len(jobs)}")
        return jobs

    # ------------------------------------------------------------------
    # Search and extraction
    # ------------------------------------------------------------------

    def build_search_url(
        self,
        keyword: str,
        location: str,
    ) -> str:
        keyword_slug = self.slugify(keyword)
        location_slug = self.slugify(location)

        return (
            f"{self.BASE_URL}/"
            f"{keyword_slug}-jobs-in-{location_slug}"
        )

    def slugify(self, value: str) -> str:
        """
        Convert a search term into a Naukri-style URL slug.
        """

        value = value.strip().lower()
        value = value.replace("&", "and")
        value = value.replace("/", " ")
        value = value.replace("-", " ")

        words = value.split()
        return "-".join(words)

    def find_job_cards(self):
        selectors = [
            "div.srp-jobtuple-wrapper",
            "article.jobTuple",
            "div[class*='jobTuple']",
            "div[class*='job-tuple']",
            "article",
        ]

        for selector in selectors:
            try:
                cards = self.page.locator(selector)

                if cards.count() > 0:
                    print(
                        f"Using Naukri card selector: "
                        f"{selector}"
                    )
                    return cards

            except Exception:
                continue

        return self.page.locator(
            "div.srp-jobtuple-wrapper"
        )

    def click_next_page(self) -> bool:
        selectors = [
            "a[aria-label='Next']",
            "button[aria-label='Next']",
            "a[rel='next']",
            "a:has-text('Next')",
            "button:has-text('Next')",
        ]

        for selector in selectors:
            try:
                next_button = self.page.locator(selector).last
                if next_button.count() == 0 or not next_button.is_visible():
                    continue
                if next_button.get_attribute("disabled") is not None:
                    return False
                next_button.click(timeout=5_000)
                self.page.wait_for_timeout(2_000)
                return True
            except Exception:
                continue

        return False

    def extract_text(
        self,
        card,
        selectors: list[str],
    ) -> str:
        for selector in selectors:
            try:
                element = card.locator(selector).first

                if element.count() == 0:
                    continue

                text = element.inner_text(
                    timeout=2_000
                ).strip()

                if text:
                    return self.clean_text(text)

            except Exception:
                continue

        return ""

    def extract_url(
        self,
        card,
        selectors: list[str],
    ) -> str:
        for selector in selectors:
            try:
                element = card.locator(selector).first

                if element.count() == 0:
                    continue

                href = element.get_attribute("href")

                if not href:
                    continue

                if href.startswith("/"):
                    return f"{self.BASE_URL}{href}"

                return href

            except Exception:
                continue

        return ""

    # Job-description containers on Naukri detail pages, most specific first.
    # The whole <body> is deliberately not used: it includes navigation and
    # "similar jobs" links whose titles would create false role matches.
    DETAIL_DESCRIPTION_SELECTORS = [
        "section[class*='job-desc']",
        "div[class*='dang-inner-html']",
        "[class*='JDC']",
        "div.job-desc",
    ]

    def enrich_job_from_detail(self, page: Page, job: Job) -> None:
        """Enrich card data from the detail page when accessible."""
        try:
            page.goto(
                job.job_url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            page.wait_for_timeout(1_000)
            if self.is_blocked_or_login_page_for(page):
                return

            detail_text = ""
            for selector in self.DETAIL_DESCRIPTION_SELECTORS:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                detail_text = self.clean_text(locator.inner_text(timeout=5_000))
                if detail_text:
                    break

            if len(detail_text) > len(job.description):
                job.description = detail_text[:20_000]
        except Exception:
            return

    def is_blocked_or_login_page_for(self, page: Page) -> bool:
        try:
            text = page.locator("body").inner_text(timeout=5_000).lower()
            url = page.url.lower()
        except Exception:
            return True

        return any(
            term in text or term in url
            for term in (
                "captcha",
                "access denied",
                "login to continue",
                "sign in to continue",
            )
        )

    def extract_posted_date(self, card) -> str:
        patterns = [
            r"just posted",
            r"today",
            r"\d+\s+hours?\s+ago",
            r"\d+\s+days?\s+ago",
            r"\d+\s+weeks?\s+ago",
        ]
        text = self.extract_text(
            card,
            [
                "[class*='date']",
                "[class*='posted']",
                "time",
            ],
        )
        text = text or self.clean_text(card.inner_text())

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(0)

        return ""

    @staticmethod
    def extract_posted_days(posted_date: str) -> int | None:
        value = posted_date.lower().strip()
        if not value:
            return None
        if "today" in value or "just posted" in value or "hour" in value:
            return 0

        match = re.search(r"(\d+)\s+days?", value)
        if match:
            return int(match.group(1))

        match = re.search(r"(\d+)\s+weeks?", value)
        if match:
            return int(match.group(1)) * 7

        return None

    # ------------------------------------------------------------------
    # Access checks
    # ------------------------------------------------------------------

    def is_blocked_or_login_page(self) -> bool:
        try:
            current_url = self.page.url.lower()

            page_text = self.page.locator(
                "body"
            ).inner_text(timeout=5_000).lower()

        except Exception:
            return False

        blocked_terms = [
            "captcha",
            "verify you are human",
            "access denied",
            "security check",
            "login to continue",
            "sign in to continue",
            "register to continue",
        ]

        return any(
            term in current_url or term in page_text
            for term in blocked_terms
        )

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def clean_text(self, value: str) -> str:
        value = value.replace("\xa0", " ")
        return " ".join(value.split())

    def save_debug_html(self, filename: str) -> None:
        debug_path = self.debug_directory / filename

        try:
            html = self.page.content()

            debug_path.write_text(
                html,
                encoding="utf-8",
            )

            print(
                f"Debug HTML saved to: "
                f"{debug_path.resolve()}"
            )

        except Exception as exc:
            print(
                f"Could not save debug HTML: {exc}"
            )
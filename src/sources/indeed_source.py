from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus, urljoin

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from src.models import Job
from src.sources.base_source import BaseJobSource


class IndeedSource(BaseJobSource):
    """
    Indeed job-search source.

    Features:
    - Searches Indeed using keyword and location.
    - Detects real job cards before checking for verification.
    - Avoids false verification detection caused by hidden page text.
    - Supports manual verification when a genuine block is displayed.
    - Collects card-level information first.
    - Opens detail pages using a separate browser page.
    """

    BASE_URL = "https://in.indeed.com"

    def __init__(
        self,
        page: Page,
        debug_directory: str = "data/debug",
        manual_verification_timeout_seconds: int = 180,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(config=config)

        self.page = page
        self.debug_directory = Path(debug_directory)
        self.debug_directory.mkdir(parents=True, exist_ok=True)

        self.manual_verification_timeout_seconds = (
            manual_verification_timeout_seconds
        )

        self.page.set_default_timeout(30000)

    @property
    def source_name(self) -> str:
        return "indeed"

    # ------------------------------------------------------------------
    # Public search method
    # ------------------------------------------------------------------

    def search_jobs(
        self,
        search_term: str,
        location: str,
        max_jobs: int = 50,
        excluded_urls: set[str] | None = None,
        max_pages: int = 1,
    ) -> list[Job]:
        """
        Search Indeed and return normalized shared Job objects.

        Indeed reads a single results page, so ``max_pages`` is accepted
        for interface compatibility only.
        """
        excluded_urls = excluded_urls or set()

        search_url = self.build_search_url(
            keyword=search_term,
            location=location,
        )

        print()
        print("Opening Indeed search page:")
        print(search_url)

        try:
            self.page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except PlaywrightTimeoutError:
            print(
                "Indeed navigation timed out. "
                "Continuing with the loaded page..."
            )
        except Exception as exc:
            print(f"Indeed navigation failed: {exc}")
            self.save_debug_html(
                "indeed_navigation_error.html",
                self.page,
            )
            return []

        time.sleep(3)

        self.accept_cookies()

        # Important:
        # Check for real job cards BEFORE checking for verification.
        # The Indeed page can contain hidden words such as "challenge"
        # or "verification" even when normal job results are available.
        if self.has_job_results():
            print("Indeed job results detected.")
        elif self.is_blocked_or_verification_page():
            verified = self.wait_for_manual_verification(
                page=self.page,
                context="search page",
            )

            if not verified:
                self.save_debug_html(
                    "indeed_search_verification_timeout.html",
                    self.page,
                )
                print(
                    "Indeed verification was not completed. "
                    "Skipping Indeed for this search."
                )
                return []

        self.wait_for_search_results()

        # Check again after waiting because the page may have changed.
        if not self.has_job_results():
            if self.is_blocked_or_verification_page():
                verified = self.wait_for_manual_verification(
                    page=self.page,
                    context="search results",
                )

                if not verified:
                    self.save_debug_html(
                        "indeed_search_results_verification_timeout.html",
                        self.page,
                    )
                    return []

        candidates = self.collect_search_cards(max_jobs)

        print(f"Indeed job cards found: {len(candidates)}")

        if not candidates:
            self.save_debug_html(
                "indeed_no_search_cards.html",
                self.page,
            )
            return []

        jobs: list[Job] = []
        detail_page: Optional[Page] = None

        try:
            # Keep the search-results page open.
            # Use another page for detail-page navigation.
            detail_page = self.page.context.new_page()
            detail_page.set_default_timeout(30000)

            for index, candidate in enumerate(candidates, start=1):
                if len(jobs) >= max_jobs:
                    break

                title = candidate.get("title", "").strip()
                job_url = candidate.get("job_url", "").strip()

                if not title:
                    print(
                        f"Skipping Indeed card {index}: "
                        "title not found"
                    )
                    continue

                if job_url in excluded_urls:
                    print(f"Skipping existing Indeed job: {job_url}")
                    continue

                print(
                    f"Processing Indeed job "
                    f"{index}/{len(candidates)}: {title}"
                )

                job = Job(
                    title=title,
                    company=candidate.get("company", ""),
                    location=candidate.get("location", ""),
                    job_url=job_url,
                    source=self.source_name,
                    salary=candidate.get("salary", ""),
                    posted_date=candidate.get("posted_date", ""),
                    posted_days=candidate.get("posted_days"),
                    job_type=candidate.get("job_type", ""),
                    description=candidate.get("description", ""),
                    card_description=candidate.get(
                        "card_description",
                        "",
                    ),
                    search_term=search_term,
                    search_location=location,
                    discovered_at=datetime.now().isoformat(
                        timespec="seconds"
                    ),
                )

                # Detail pages are optional. If a detail page fails,
                # retain the card-level job information.
                if job_url:
                    detail_data = self.extract_job_details(
                        page=detail_page,
                        job_data=job.to_dict(),
                    )
                    job = self.job_from_dict(detail_data)

                job = self.normalize_job(job)
                jobs.append(job)

                print(
                    f"Collected Indeed job {len(jobs)}: "
                    f"{job.title} | {job.company}"
                )

                time.sleep(1)

        finally:
            if detail_page is not None:
                try:
                    if not detail_page.is_closed():
                        detail_page.close()
                except Exception:
                    pass

        print(f"Indeed jobs extracted: {len(jobs)}")
        return jobs

    # ------------------------------------------------------------------
    # URL and page handling
    # ------------------------------------------------------------------

    def build_search_url(
        self,
        keyword: str,
        location: str,
    ) -> str:
        return (
            f"{self.BASE_URL}/jobs"
            f"?q={quote_plus(keyword)}"
            f"&l={quote_plus(location)}"
        )

    def accept_cookies(self) -> None:
        """
        Attempt to close common cookie-consent buttons.
        """

        selectors = [
            "#onetrust-accept-btn-handler",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('Agree')",
            "[data-testid='cookie-accept']",
        ]

        for selector in selectors:
            try:
                button = self.page.locator(selector).first

                if button.count() > 0 and button.is_visible():
                    button.click(timeout=3000)
                    print("Indeed cookie banner accepted.")
                    time.sleep(1)
                    return

            except Exception:
                continue

    def wait_for_search_results(self) -> None:
        """
        Wait briefly for normal job-result selectors.

        This method does not raise an exception when no selector appears.
        """

        selectors = [
            "div.job_seen_beacon",
            "div[data-testid='slider_item']",
            "a[data-jk]",
            "td.resultContent",
            "div.cardOutline",
            "h2.jobTitle",
        ]

        for selector in selectors:
            try:
                locator = self.page.locator(selector)

                if locator.count() > 0:
                    locator.first.wait_for(
                        state="visible",
                        timeout=5000,
                    )
                    return

            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue

        time.sleep(2)

    def has_job_results(self) -> bool:
        """
        Return True when actual Indeed job-result elements exist.
        """

        if self.page.is_closed():
            return False

        selectors = [
            "div.job_seen_beacon",
            "a[data-jk]",
            "td.resultContent",
            "div.cardOutline",
            "h2.jobTitle",
            "a[href*='/viewjob']",
            "a[href*='/rc/clk']",
        ]

        for selector in selectors:
            try:
                if self.page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue

        return False

    # ------------------------------------------------------------------
    # Verification and blocking detection
    # ------------------------------------------------------------------

    def is_blocked_or_verification_page(
        self,
        page: Optional[Page] = None,
    ) -> bool:
        """
        Detect genuine verification or access-block pages.

        Important:
        - Do not use generic terms such as "challenge" or "robot".
        - Do not inspect the complete HTML source.
        - Hidden scripts and metadata can contain misleading words.
        - If job cards exist, the page is treated as a results page.
        """

        current_page = page or self.page

        try:
            if current_page.is_closed():
                return True
        except Exception:
            return True

        # A page with actual job cards should never be classified
        # as a verification page.
        result_selectors = [
            "div.job_seen_beacon",
            "a[data-jk]",
            "td.resultContent",
            "div.cardOutline",
            "h2.jobTitle",
            "a[href*='/viewjob']",
            "a[href*='/rc/clk']",
        ]

        for selector in result_selectors:
            try:
                if current_page.locator(selector).count() > 0:
                    return False
            except Exception:
                continue

        try:
            body_text = (
                current_page.locator("body")
                .inner_text(timeout=5000)
                .lower()
            )
        except Exception:
            body_text = ""

        try:
            current_url = current_page.url.lower()
        except Exception:
            current_url = ""

        specific_indicators = [
            "verify you are human",
            "verify that you are human",
            "confirm you are human",
            "complete the security check",
            "security check",
            "captcha",
            "robot check",
            "unusual traffic",
            "access denied",
            "temporarily blocked",
        ]

        for indicator in specific_indicators:
            if indicator in body_text or indicator in current_url:
                return True

        return False

    def wait_for_manual_verification(
        self,
        page: Page,
        context: str = "",
    ) -> bool:
        """
        Wait for the user to complete a genuine manual verification step.
        """

        print()
        print("=" * 72)
        print("Indeed requires manual human verification.")
        print(f"Context: {context}")
        print()
        print("Please complete the verification in the browser.")
        print("The script will wait automatically.")
        print(
            "Timeout: "
            f"{self.manual_verification_timeout_seconds} seconds"
        )
        print("=" * 72)
        print()

        deadline = (
            time.monotonic()
            + self.manual_verification_timeout_seconds
        )

        while time.monotonic() < deadline:
            try:
                if page.is_closed():
                    return False
            except Exception:
                return False

            # If real job cards appear, verification is effectively done.
            if self.has_job_results():
                print("Indeed job results are now available.")
                return True

            if not self.is_blocked_or_verification_page(page):
                print("Manual verification appears completed.")
                time.sleep(2)
                return True

            time.sleep(2)

        print("Manual verification timeout reached.")
        return False

    # ------------------------------------------------------------------
    # Search-card extraction
    # ------------------------------------------------------------------

    def collect_search_cards(
        self,
        max_jobs: int,
    ) -> list[dict[str, str]]:
        """
        Collect card information without navigating away from the
        search-results page.
        """

        selectors = [
            "div.job_seen_beacon",
            "td.resultContent",
            "div.cardOutline",
            "div[data-testid='slider_item']",
        ]

        cards = None

        for selector in selectors:
            try:
                locator = self.page.locator(selector)

                if locator.count() > 0:
                    cards = locator
                    print(
                        f"Using Indeed card selector: {selector}"
                    )
                    break

            except Exception:
                continue

        if cards is None:
            return []

        candidates: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        card_count = min(cards.count(), max_jobs)

        for index in range(card_count):
            card = cards.nth(index)

            try:
                title = self.extract_card_title(card)

                if not title:
                    continue

                job_url = self.extract_card_url(card)

                if job_url and job_url in seen_urls:
                    continue

                if job_url:
                    seen_urls.add(job_url)

                candidate = {
                    "title": title,
                    "company": self.extract_card_text(
                        card,
                        [
                            "[data-testid='company-name']",
                            ".companyName",
                            "[class*='companyName']",
                        ],
                    ),
                    "location": self.extract_card_text(
                        card,
                        [
                            "[data-testid='text-location']",
                            ".companyLocation",
                            "[class*='companyLocation']",
                        ],
                    ),
                    "salary": self.extract_card_text(
                        card,
                        [
                            "[data-testid*='salary-snippet-container']",
                            ".salary-snippet-container",
                            "[class*='salary-snippet']",
                            "[class*='salarySnippet']",
                        ],
                    ),
                    "job_type": self.extract_card_job_type(card),
                    "description": self.extract_card_description(card),
                    "card_description": self.extract_card_description(
                        card
                    ),
                    "posted_date": self.extract_card_posted_date(card),
                    "posted_days": "",
                    "job_url": job_url,
                }

                candidate["posted_days"] = self.extract_posted_days(
                    candidate["posted_date"]
                )

                candidates.append(candidate)

            except Exception as exc:
                print(
                    f"Could not extract Indeed card "
                    f"{index + 1}: {exc}"
                )

        return candidates

    def extract_card_title(self, card: Any) -> str:
        selectors = [
            "h2.jobTitle",
            "h3.jobTitle",
            "[data-testid='job-title']",
            "a[data-jk]",
            "a[href*='/rc/clk']",
        ]

        for selector in selectors:
            try:
                locator = card.locator(selector).first

                if locator.count() > 0:
                    text = locator.inner_text(timeout=3000).strip()

                    if text:
                        return self.clean_text(text)

                    aria_label = locator.get_attribute("aria-label")

                    if aria_label:
                        return self.clean_text(
                            aria_label.replace(
                                "full details of",
                                "",
                            )
                        )

            except Exception:
                continue

        return ""

    def extract_card_url(self, card: Any) -> str:
        selectors = [
            "h2.jobTitle a",
            "h3.jobTitle a",
            "a[data-jk]",
            "a[href*='/rc/clk']",
            "a[href*='/viewjob']",
        ]

        for selector in selectors:
            try:
                locator = card.locator(selector).first

                if locator.count() == 0:
                    continue

                href = locator.get_attribute("href")

                if href:
                    return urljoin(self.BASE_URL, href)

            except Exception:
                continue

        return ""

    def extract_card_text(
        self,
        card: Any,
        selectors: list[str],
    ) -> str:
        for selector in selectors:
            try:
                locator = card.locator(selector).first

                if locator.count() > 0:
                    text = locator.inner_text(timeout=3000).strip()

                    if text:
                        return self.clean_text(text)

            except Exception:
                continue

        return ""

    def extract_card_job_type(self, card: Any) -> str:
        text = self.extract_card_text(
            card,
            [
                "[data-testid*='job-type']",
                "[class*='jobType']",
                "[class*='job-type']",
            ],
        )

        if text:
            return text

        full_text = self.safe_inner_text(card)

        job_types = [
            "full-time",
            "part-time",
            "contract",
            "temporary",
            "internship",
            "permanent",
        ]

        found = []

        for job_type in job_types:
            if job_type in full_text.lower():
                found.append(job_type.title())

        return ", ".join(dict.fromkeys(found))

    def extract_card_description(self, card: Any) -> str:
        description = self.extract_card_text(
            card,
            [
                "[data-testid='job-snippet']",
                ".job-snippet",
                ".underShelfFooter",
                "[class*='job-snippet']",
                "[class*='jobSnippet']",
            ],
        )
        if description:
            return description

        # Some India result cards omit the snippet selector while still
        # exposing useful text in the card body.
        card_text = self.safe_inner_text(card)
        title = self.extract_card_title(card)
        company = self.extract_card_text(
            card,
            [
                "[data-testid='company-name']",
                ".companyName",
                "[class*='companyName']",
            ],
        )
        location = self.extract_card_text(
            card,
            [
                "[data-testid='text-location']",
                ".companyLocation",
                "[class*='companyLocation']",
            ],
        )
        for value in (title, company, location):
            card_text = card_text.replace(value, "")
        return self.clean_text(card_text)

    def extract_card_posted_date(self, card: Any) -> str:
        text = self.extract_card_text(
            card,
            [
                "[data-testid='myJobsStateDate']",
                "[class*='date']",
                ".date",
                "span",
            ],
        )

        patterns = [
            r"\btoday\b",
            r"\bjust posted\b",
            r"\b\d+\s+days?\s+ago\b",
            r"\b\d+\s+hours?\s+ago\b",
            r"\b\d+\s+minutes?\s+ago\b",
            r"\b30\+\s+days?\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)

            if match:
                return match.group(0)

        full_text = self.safe_inner_text(card)

        for pattern in patterns:
            match = re.search(
                pattern,
                full_text,
                flags=re.IGNORECASE,
            )

            if match:
                return match.group(0)

        return ""

    def extract_posted_days(self, posted_date: str) -> str:
        if not posted_date:
            return ""

        value = posted_date.lower().strip()

        if "today" in value or "just posted" in value:
            return "0"

        match = re.search(r"(\d+)\s+days?", value)

        if match:
            return match.group(1)

        match = re.search(r"(\d+)\s+hours?", value)

        if match:
            return "0"

        match = re.search(r"(\d+)\s+minutes?", value)

        if match:
            return "0"

        if "30+" in value:
            return "30+"

        return ""

    # ------------------------------------------------------------------
    # Detail-page extraction
    # ------------------------------------------------------------------

    def extract_job_details(
        self,
        page: Page,
        job_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Attempt to enrich a job using its detail page.

        If Indeed blocks or redirects the detail page, the original
        card-level data is returned unchanged.
        """

        job_url = job_data.get("job_url", "")

        if not job_url:
            return job_data

        try:
            page.goto(
                job_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            time.sleep(2)

            if self.is_blocked_or_verification_page(page):
                return job_data

            detail_description = self.extract_detail_description(page)

            if detail_description:
                job_data["description"] = detail_description

            detail_company = self.extract_detail_company(page)

            if detail_company:
                job_data["company"] = detail_company

            detail_location = self.extract_detail_location(page)

            if detail_location:
                job_data["location"] = detail_location

        except Exception as exc:
            print(
                "Indeed detail-page extraction skipped: "
                f"{type(exc).__name__}"
            )

        return job_data

    def extract_detail_description(self, page: Page) -> str:
        selectors = [
            "#jobDescriptionText",
            "[data-testid='jobDescriptionText']",
            ".jobsearch-JobComponent-description",
            "[class*='jobDescription']",
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector).first

                if locator.count() > 0:
                    text = locator.inner_text(timeout=5000).strip()

                    if text:
                        return self.clean_text(text)

            except Exception:
                continue

        return ""

    def extract_detail_company(self, page: Page) -> str:
        selectors = [
            "[data-testid='inlineHeader-companyName']",
            "[data-testid='companyName']",
            "[class*='companyName']",
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector).first

                if locator.count() > 0:
                    text = locator.inner_text(timeout=3000).strip()

                    if text:
                        return self.clean_text(text)

            except Exception:
                continue

        return ""

    def extract_detail_location(self, page: Page) -> str:
        selectors = [
            "[data-testid='inlineHeader-companyLocation']",
            "[data-testid='job-location']",
            "[class*='companyLocation']",
        ]

        for selector in selectors:
            try:
                locator = page.locator(selector).first

                if locator.count() > 0:
                    text = locator.inner_text(timeout=3000).strip()

                    if text:
                        return self.clean_text(text)

            except Exception:
                continue

        return ""

    # ------------------------------------------------------------------
    # Shared model conversion
    # ------------------------------------------------------------------

    def job_from_dict(self, data: dict[str, Any]) -> Job:
        allowed_fields = set(Job.__dataclass_fields__.keys())

        filtered_data = {
            key: value
            for key, value in data.items()
            if key in allowed_fields
        }

        return Job(**filtered_data)

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def safe_inner_text(self, locator: Any) -> str:
        try:
            return self.clean_text(
                locator.inner_text(timeout=3000)
            )
        except Exception:
            return ""

    def clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def save_debug_html(
        self,
        filename: str,
        page: Optional[Page] = None,
    ) -> None:
        current_page = page or self.page
        output_path = self.debug_directory / filename

        try:
            if current_page.is_closed():
                return

            html = current_page.content()
            output_path.write_text(
                html,
                encoding="utf-8",
            )

            print(
                f"Saved Indeed debug HTML: {output_path}"
            )

        except Exception as exc:
            print(
                f"Could not save Indeed debug HTML: {exc}"
            )
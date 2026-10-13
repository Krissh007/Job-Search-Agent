"""
Offline tests for the LinkedIn adapter. Network calls are replaced with
local markup copied from LinkedIn's public job pages (Sep 2026).
"""

import pytest
from playwright.sync_api import sync_playwright

from src.sources.linkedin_source import LinkedInSource


def card(job_id: str, title: str, company: str, posted: str) -> str:
    return f"""
    <li><div class="base-card base-search-card" data-entity-urn="urn:li:jobPosting:{job_id}">
      <a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/x-{job_id}?position=1&trackingId=abc"></a>
      <div class="base-search-card__info">
        <h3 class="base-search-card__title"> {title} </h3>
        <h4 class="base-search-card__subtitle"><a>{company}</a></h4>
        <div class="base-search-card__metadata">
          <span class="job-search-card__location">Hyderabad, Telangana, India</span>
          <time class="job-search-card__listdate" datetime="{posted}">2 days ago</time>
        </div>
      </div>
    </div></li>"""


SEARCH_PAGE = card("4472713530", "Senior Business Analyst", "HTC Global Services", "2026-09-27") + card(
    "4472713531", "Product Analyst", "Beta SaaS", "2026-09-28"
)

POSTING_PAGE = """
<div class="show-more-less-html__markup">
  Gather business requirements.<br><br>
  3-5 years of experience with SQL and UAT.
</div>
<ul>
  <li class="description__job-criteria-item"><h3>Seniority level</h3><span>Associate</span></li>
  <li class="description__job-criteria-item"><h3>Employment type</h3><span>Full-time</span></li>
</ul>
"""


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser.new_page()
        browser.close()


@pytest.fixture
def source(page, tmp_path, monkeypatch):
    linkedin = LinkedInSource(page, enrich_details=True, debug_directory=str(tmp_path), delay_ms=0)
    pages = {"search_0": SEARCH_PAGE, "search_10": ""}

    def fake_get(url: str):
        if "jobPosting" in url:
            return POSTING_PAGE
        start = url.split("start=")[1].split("&")[0]
        return pages.get(f"search_{start}", "")

    monkeypatch.setattr(linkedin, "_get", fake_get)
    return linkedin


def test_search_url_filters_by_posting_age():
    linkedin = LinkedInSource.__new__(LinkedInSource)
    linkedin.posted_within_days = 7
    url = linkedin.search_url("Business Analyst", "Hyderabad", start=10)
    assert "keywords=Business+Analyst" in url
    assert "location=Hyderabad%2C+India" in url
    assert "f_TPR=r604800" in url
    assert "start=10" in url


def test_cards_become_jobs_with_canonical_urls(source):
    jobs = source.search_jobs("Business Analyst", "Hyderabad", max_jobs=10)

    assert [job.title for job in jobs] == ["Senior Business Analyst", "Product Analyst"]
    first = jobs[0]
    # Tracking parameters are dropped so the same job de-duplicates.
    assert first.job_url == "https://www.linkedin.com/jobs/view/4472713530"
    assert first.company == "HTC Global Services"
    assert first.location == "Hyderabad, Telangana, India"
    assert first.posted_date == "2026-09-27"
    assert first.source == "linkedin"


def test_posting_details_are_added(source):
    first = source.search_jobs("Business Analyst", "Hyderabad", max_jobs=1)[0]

    assert "3-5 years of experience" in first.description
    assert first.job_type == "Associate · Full-time"


def test_known_jobs_are_skipped(source):
    jobs = source.search_jobs(
        "Business Analyst",
        "Hyderabad",
        excluded_urls={"https://www.linkedin.com/jobs/view/4472713530"},
    )
    assert [job.title for job in jobs] == ["Product Analyst"]


class _Response:
    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self._body = body

    def text(self) -> str:
        return self._body


def test_rate_limit_is_retried_after_backoff(page, tmp_path, monkeypatch):
    linkedin = LinkedInSource(page, debug_directory=str(tmp_path), delay_ms=0)
    monkeypatch.setattr(LinkedInSource, "RATE_LIMIT_BACKOFF_MS", (0, 0))
    responses = iter([_Response(429), _Response(200, "ok")])
    monkeypatch.setattr(linkedin, "_request", lambda url: next(responses))

    assert linkedin._get("https://example.com") == "ok"


def test_persistent_rate_limit_gives_up(page, tmp_path, monkeypatch):
    linkedin = LinkedInSource(page, debug_directory=str(tmp_path), delay_ms=0)
    monkeypatch.setattr(LinkedInSource, "RATE_LIMIT_BACKOFF_MS", (0, 0))
    monkeypatch.setattr(linkedin, "_request", lambda url: _Response(429))

    assert linkedin._get("https://example.com") is None

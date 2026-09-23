"""
Smoke test for the Naukri card parser (ISS-8).

Requests to naukri.com are intercepted and answered with a local copy of
the search-results markup, so no network access is needed. If Naukri
changes its layout, update SEARCH_HTML from a saved data/debug page.
"""

import pytest
from playwright.sync_api import sync_playwright

from src.sources.naukri_source import NaukriSource

SEARCH_HTML = """
<html><body>
  <div class="srp-jobtuple-wrapper">
    <a class="title" href="/job-listings-business-analyst-acme-hyderabad-3-to-5-years-1">Business Analyst</a>
    <a class="comp-name">Acme Analytics</a>
    <span class="expwdth">3-5 Yrs</span>
    <span class="sal">8-12 Lacs PA</span>
    <span class="locWdth">Hyderabad</span>
    <span class="job-desc">Requirements gathering, UAT and SQL.</span>
    <span class="job-post-day">3 Days Ago</span>
  </div>
  <div class="srp-jobtuple-wrapper">
    <a class="title" href="https://www.naukri.com/job-listings-product-analyst-beta-2">Product Analyst</a>
    <a class="comp-name">Beta SaaS</a>
    <span class="expwdth">2-4 Yrs</span>
    <span class="locWdth">Hyderabad</span>
    <span class="job-post-day">Just Now</span>
  </div>
  <div class="srp-jobtuple-wrapper">
    <a class="title" href="/job-listings-known-job-3">Known Job</a>
  </div>
</body></html>
"""


@pytest.fixture(scope="module")
def jobs(tmp_path_factory):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route(
            "**/*",
            lambda route: route.fulfill(status=200, content_type="text/html", body=SEARCH_HTML),
        )
        source = NaukriSource(
            page=page,
            debug_directory=str(tmp_path_factory.mktemp("debug")),
        )
        result = source.search_jobs(
            search_term="Business Analyst",
            location="Hyderabad",
            max_jobs=10,
            excluded_urls={"https://www.naukri.com/job-listings-known-job-3"},
            max_pages=1,
        )
        browser.close()
    return result


def test_reads_every_new_card(jobs):
    assert [job.title for job in jobs] == ["Business Analyst", "Product Analyst"]


def test_card_fields(jobs):
    first = jobs[0]
    assert first.company == "Acme Analytics"
    assert first.location == "Hyderabad"
    assert first.experience == "3-5 Yrs"
    assert first.salary == "8-12 Lacs PA"
    assert first.posted_days == 3
    assert first.source == "naukri"
    assert first.search_term == "Business Analyst"


def test_relative_urls_are_made_absolute(jobs):
    assert jobs[0].job_url.startswith("https://www.naukri.com/job-listings-")


def test_known_urls_are_skipped(jobs):
    assert all("known-job" not in job.job_url for job in jobs)


def test_search_url_slug(tmp_path):
    source = NaukriSource(page=None, debug_directory=str(tmp_path))
    assert (
        source.build_search_url("AI Business Analyst", "Hyderabad")
        == "https://www.naukri.com/ai-business-analyst-jobs-in-hyderabad"
    )

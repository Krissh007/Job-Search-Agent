from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from src.sources.naukri_source import NaukriSource


def main() -> None:
    keyword = "business analyst"
    location = "Hyderabad"
    max_jobs = 16

    print("=" * 80)
    print("STARTING NAUKRI SOURCE TEST")
    print("=" * 80)
    print(f"Keyword: {keyword}")
    print(f"Location: {location}")
    print(f"Maximum jobs: {max_jobs}")
    print()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900,
            },
            locale="en-IN",
        )

        page = context.new_page()

        try:
            source = NaukriSource(
                page=page,
                keyword=keyword,
                location=location,
            )

            jobs = source.discover_jobs(
                max_jobs=max_jobs
            )

            print()
            print("=" * 80)
            print("NAUKRI TEST SUMMARY")
            print("=" * 80)
            print(f"Jobs discovered: {len(jobs)}")

            for index, job in enumerate(jobs, start=1):
                print()
                print(f"{index}. {job.title}")
                print(f"   Company: {job.company}")
                print(f"   Location: {job.location}")
                print(f"   URL: {job.job_url}")
                print(f"   Salary: {job.salary}")
                print(f"   Experience: {job.job_type}")

        finally:
            browser.close()
            print()
            print("Browser closed successfully.")


if __name__ == "__main__":
    main()
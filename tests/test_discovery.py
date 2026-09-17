from playwright.sync_api import sync_playwright

from src.discovery import JobDiscovery


TEST_HTML = """
<html>
<body>
    <div class="job-card">
        <a href="https://example.com/jobs/1">
            <span class="job-title">AI Business Analyst</span>
        </a>
        <span class="company">Example Analytics</span>
        <span class="location">Hyderabad</span>
    </div>

    <div class="job-card">
        <a href="https://example.com/jobs/2">
            <span class="job-title">Product Analyst</span>
        </a>
        <span class="company">Example SaaS</span>
        <span class="location">Remote</span>
    </div>
</body>
</html>
"""


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        page.set_content(TEST_HTML)

        discovery = JobDiscovery(page)
        jobs = discovery.discover_jobs()

        print(f"Discovered jobs: {len(jobs)}")

        for job in jobs:
            print(
                f"- {job.title} | {job.company} | "
                f"{job.location} | {job.job_url}"
            )

        browser.close()


if __name__ == "__main__":
    main()
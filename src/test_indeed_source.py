from pathlib import Path

from playwright.sync_api import sync_playwright

from src.sources.indeed_source import IndeedSource


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    logs_directory = project_root / "data" / "logs"

    logs_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
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
            source = IndeedSource(
                page=page,
                keyword="business analyst",
                location="Hyderabad",
            )

            jobs = source.discover_jobs(
                max_jobs=16,
            )

            print()
            print("=" * 80)
            print(f"Total jobs collected: {len(jobs)}")
            print("=" * 80)

            for index, job in enumerate(jobs, start=1):
                print()
                print(f"Job {index}")
                print(f"Title: {job.title}")
                print(f"Company: {job.company}")
                print(f"Location: {job.location}")
                print(f"Salary: {job.salary}")
                print(f"Job type: {job.job_type}")
                print(f"URL: {job.job_url}")
                print(
                    "Description length: "
                    f"{len(job.description)} characters"
                )

            debug_path = logs_directory / "indeed_debug.html"

            debug_path.write_text(
                page.content(),
                encoding="utf-8",
            )

            print()
            print(f"Saved complete page HTML to: {debug_path}")

        finally:
            browser.close()
            print("Browser closed successfully.")


if __name__ == "__main__":
    main()
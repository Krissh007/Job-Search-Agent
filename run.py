from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config_manager import ConfigManager
from src.sources.indeed_source import IndeedSource
from src.sources.naukri_source import NaukriSource


def main() -> None:
    project_root = Path(__file__).resolve().parent
    config_path = project_root / "config" / "settings.yaml"

    config_manager = ConfigManager(config_path)
    config = config_manager.all()

    browser_config = config.get("browser", {})
    search_config = config.get("search", {})
    sources_config = config.get("sources", [])

    headless = browser_config.get("headless", False)
    default_timeout = browser_config.get(
        "default_timeout_ms",
        30_000,
    )
    navigation_timeout = browser_config.get(
        "navigation_timeout_ms",
        60_000,
    )

    keywords = search_config.get("keywords", [])
    locations = search_config.get("locations", [])
    max_results = search_config.get(
        "max_results_per_query",
        50,
    )

    print("Job Search Agent started")
    print(f"Keywords: {keywords}")
    print(f"Locations: {locations}")
    print(f"Sources: {sources_config}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
        )

        context = browser.new_context()

        context.set_default_timeout(default_timeout)
        context.set_default_navigation_timeout(
            navigation_timeout
        )

        indeed_page = context.new_page()
        naukri_page = context.new_page()

        all_jobs = []

        for keyword in keywords:
            for location in locations:
                print("\n" + "=" * 60)
                print(
                    f"Searching: {keyword} | {location}"
                )
                print("=" * 60)

                if "indeed" in sources_config:
                    print("\nStarting Indeed search...")

                    indeed_source = IndeedSource(
                        page=indeed_page,
                    )

                    indeed_jobs = indeed_source.search_jobs(
                        search_term=keyword,
                        location=location,
                        max_jobs=max_results,
                    )

                    all_jobs.extend(indeed_jobs)

                    print(
                        f"Indeed jobs collected: "
                        f"{len(indeed_jobs)}"
                    )

                if "naukri" in sources_config:
                    print("\nStarting Naukri search...")

                    naukri_source = NaukriSource(
                        page=naukri_page,
                    )

                    naukri_jobs = naukri_source.search_jobs(
                        search_term=keyword,
                        location=location,
                        max_jobs=max_results,
                    )

                    all_jobs.extend(naukri_jobs)

                    print(
                        f"Naukri jobs collected: "
                        f"{len(naukri_jobs)}"
                    )

        print("\n" + "=" * 60)
        print(
            f"Total jobs collected: {len(all_jobs)}"
        )
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    main()
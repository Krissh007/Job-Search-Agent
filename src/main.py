from __future__ import annotations

import logging
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config_manager import ConfigManager
from .resume_profile import load_resume_profile
from .matching.job_matcher import JobMatcher
from .storage import JobStorage
from .sources.indeed_source import IndeedSource


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"
MATCHING_RULES_PATH = PROJECT_ROOT / "config" / "matching_rules.yaml"


def configure_logging(config: dict) -> None:
    project_config = config.get("project", {})

    log_directory = (
        PROJECT_ROOT
        / project_config.get("log_directory", "data/logs")
    )

    log_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    log_file = log_directory / "job_search_agent.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(
                log_file,
                encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def main() -> None:
    print("=" * 72)
    print("JOB SEARCH AGENT")
    print("=" * 72)

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file was not found:\n{CONFIG_PATH}"
        )

    if not MATCHING_RULES_PATH.exists():
        raise FileNotFoundError(
            f"Matching rules file was not found:\n{MATCHING_RULES_PATH}"
        )

    config = ConfigManager(CONFIG_PATH).all()
    configure_logging(config)

    logger = logging.getLogger(__name__)

    browser_config = config.get("browser", {})
    search_config = config.get("search", {})

    keywords = search_config.get(
        "keywords",
        ["business analyst"],
    )

    locations = search_config.get(
        "locations",
        ["Hyderabad"],
    )

    max_results_per_query = int(
        search_config.get(
            "max_results_per_query",
            60,
        )
    )

    minimum_match_score = float(
        search_config.get(
            "minimum_match_score",
            45,
        )
    )

    headless = bool(
        browser_config.get(
            "headless",
            False,
        )
    )

    default_timeout_ms = int(
        browser_config.get(
            "default_timeout_ms",
            30000,
        )
    )

    navigation_timeout_ms = int(
        browser_config.get(
            "navigation_timeout_ms",
            60000,
        )
    )

    print(f"Configuration: {CONFIG_PATH}")
    print(f"Matching rules: {MATCHING_RULES_PATH}")
    print(f"Keywords: {', '.join(keywords)}")
    print(f"Locations: {', '.join(locations)}")
    print(f"Maximum results per query: {max_results_per_query}")
    print(f"Minimum match score: {minimum_match_score}")
    print()

    logger.info("Project root: %s", PROJECT_ROOT)
    logger.info("Configuration: %s", CONFIG_PATH)
    logger.info("Matching rules: %s", MATCHING_RULES_PATH)
    logger.info("Keywords: %s", keywords)
    logger.info("Locations: %s", locations)

    storage = JobStorage(
        PROJECT_ROOT,
        config,
    )

    # JobMatcher expects positional arguments.
    matching_rules = ConfigManager(MATCHING_RULES_PATH).all()
    profile_path = PROJECT_ROOT / "config" / "candidate_profile.yaml"
    resume_profile = load_resume_profile(profile_path)
    matcher = JobMatcher(
        resume_profile=resume_profile,
        matching_rules=matching_rules,
    )

    all_jobs: list[dict] = []

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None

        try:
            browser = playwright.chromium.launch(
                headless=headless,
            )

            context = browser.new_context(
                viewport={
                    "width": 1440,
                    "height": 1000,
                },
                locale="en-US",
                timezone_id="Asia/Kolkata",
            )

            context.set_default_timeout(
                default_timeout_ms,
            )

            context.set_default_navigation_timeout(
                navigation_timeout_ms,
            )

            page = context.new_page()

            page.set_default_timeout(
                default_timeout_ms,
            )

            page.set_default_navigation_timeout(
                navigation_timeout_ms,
            )

            logger.info("Browser started.")

            for keyword in keywords:
                for location in locations:
                    print("-" * 72)
                    print(
                        f"Searching Indeed for: "
                        f"{keyword} | {location}"
                    )
                    print("-" * 72)

                    logger.info(
                        "Searching Indeed for '%s' in '%s'",
                        keyword,
                        location,
                    )

                    indeed_source = IndeedSource(
                        page=page,
                    )

                    discovered_jobs = indeed_source.discover_jobs(
                        keyword=keyword,
                        location=location,
                        max_jobs=max_results_per_query,
                    )

                    logger.info(
                        "Indeed returned %s jobs.",
                        len(discovered_jobs),
                    )

                    for job in discovered_jobs:
                        job["search_keyword"] = keyword
                        job["search_location"] = location

                        try:
                            enriched_job = matcher.enrich_job(job)

                            score = float(
                                enriched_job.get(
                                    "match_score",
                                    0,
                                )
                                or 0
                            )

                            if score >= minimum_match_score:
                                all_jobs.append(enriched_job)

                                logger.info(
                                    "Accepted job: %s | %s | Score: %.1f",
                                    enriched_job.get("title", ""),
                                    enriched_job.get("company", ""),
                                    score,
                                )
                            else:
                                logger.info(
                                    "Skipped low-score job: %s | Score: %.1f",
                                    enriched_job.get("title", ""),
                                    score,
                                )

                        except Exception as exc:
                            logger.exception(
                                "Could not match job '%s': %s",
                                job.get("title", ""),
                                exc,
                            )

        except KeyboardInterrupt:
            print()
            print("Scraping stopped by user.")
            logger.warning("Scraping stopped by user.")

        except Exception as exc:
            logger.exception(
                "Unexpected scraper error: %s",
                exc,
            )
            raise

        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

            logger.info("Browser closed.")

    print()
    print("=" * 72)
    print("SAVING RESULTS")
    print("=" * 72)

    if not all_jobs:
        print("No jobs matched the configured minimum score.")
        logger.info("No matching jobs found.")
        return

    try:
        saved_jobs = storage.save_jobs(all_jobs)

        print(f"Jobs saved: {saved_jobs}")

        export_path = storage.export_to_excel("job_search_results.xlsx")
        print(f"Excel export: {export_path}")

        logger.info(
            "Saved %s jobs to storage.",
            len(saved_jobs),
        )

    except PermissionError:
        print()
        print("ERROR: The Excel export file is locked.")
        print(
            "Close job_search_results.xlsx in Excel, "
            "LibreOffice, or any file preview."
        )

        logger.exception(
            "Permission denied while saving job results.",
        )

    except Exception as exc:
        logger.exception(
            "Could not save jobs: %s",
            exc,
        )

        print(f"Could not save jobs: {exc}")


if __name__ == "__main__":
    main()
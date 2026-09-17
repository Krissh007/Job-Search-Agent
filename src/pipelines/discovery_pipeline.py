from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from playwright.sync_api import sync_playwright

from src.config_manager import load_config
from src.database import Database
from src.discovery import JobDiscovery
from src.freshness import posted_age_days
from src.application_queue import (
    create_application_review_page,
    excel_review_link,
    prepare_new_applications,
)
from src.application_tracking import upsert_application_record
from src.normalizer import JobNormalizer
from src.reports.export_excel import (
    export_daily_new_leads,
    export_master_jobs,
)
from src.resume_profile import load_resume_profile
from src.matching.job_matcher import JobMatcher
from src.sources.indeed_source import IndeedSource
from src.sources.naukri_source import NaukriSource


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_project_path(path_value: str) -> Path:
    """
    Resolve a project-relative path from the project root.
    """
    path = Path(path_value)

    if path.is_absolute():
        return path

    return PROJECT_ROOT / path


def get_nested(
    data: Dict[str, Any],
    section: str,
    key: str,
    default: Any = None,
) -> Any:
    """
    Safely read a nested configuration value.
    """
    section_data = data.get(section, {})

    if not isinstance(section_data, dict):
        return default

    return section_data.get(key, default)


def create_source(
    source_name: str,
    page: Any,
    keyword: str,
    location: str,
) -> Any:
    """
    Create the correct source adapter.
    """
    source_name = source_name.lower().strip()

    if source_name == "indeed":
        return IndeedSource(page=page)

    if source_name == "naukri":
        return NaukriSource(
            page=page,
            keyword=keyword,
            location=location,
        )

    raise ValueError(
        f"Unsupported source configured: {source_name}"
    )


class DiscoveryPipeline:
    """Run discovery, normalization, matching, and persistence."""

    def __init__(
        self,
        page: Any,
        project_root: str | Path,
        database_path: str | Path,
    ) -> None:
        self.page = page
        self.project_root = Path(project_root)
        self.database = Database(database_path)

    def run(self) -> int:
        settings = load_config(
            self.project_root / "config" / "settings.yaml"
        )
        matching_rules = load_config(
            self.project_root / "config" / "matching_rules.yaml"
        )
        resume_profile = load_resume_profile(
            self.project_root / "config" / "candidate_profile.yaml"
        )

        normalizer = JobNormalizer(settings=settings)
        matcher = JobMatcher(
            resume_profile=resume_profile,
            matching_rules=matching_rules,
        )

        saved_count = 0
        for discovered_job in JobDiscovery(self.page).discover_jobs():
            normalized_job = normalizer.normalize(discovered_job)
            match_result = matcher.match(normalized_job)
            final_job = {
                **normalized_job,
                **match_result,
            }

            if final_job["job_url"]:
                self.database.save_job(final_job)
                saved_count += 1

        return saved_count


def main() -> None:
    print("=" * 80)
    print("STARTING MULTI-PORTAL JOB DISCOVERY PIPELINE")
    print("=" * 80)

    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    profile_path = PROJECT_ROOT / "config" / "candidate_profile.yaml"
    rules_path = PROJECT_ROOT / "config" / "matching_rules.yaml"

    settings = load_config(settings_path)
    matching_rules = load_config(rules_path)
    resume_profile = load_resume_profile(profile_path)

    project_database_path = get_nested(
        settings,
        "project",
        "database_path",
        "data/jobs.db",
    )

    database_path = resolve_project_path(
        project_database_path
    )

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    browser_headless = get_nested(
        settings,
        "browser",
        "headless",
        False,
    )

    default_timeout_ms = get_nested(
        settings,
        "browser",
        "default_timeout_ms",
        30_000,
    )

    navigation_timeout_ms = get_nested(
        settings,
        "browser",
        "navigation_timeout_ms",
        60_000,
    )

    search_keywords = get_nested(
        settings,
        "search",
        "keywords",
        ["business analyst"],
    )

    search_locations = get_nested(
        settings,
        "search",
        "locations",
        ["Hyderabad"],
    )

    max_jobs_per_source = get_nested(
        settings,
        "search",
        "max_results_per_query",
        60,
    )
    max_pages_per_source = get_nested(
        settings,
        "search",
        "max_pages_per_source",
        10,
    )

    enabled_sources = settings.get(
        "sources",
        ["indeed", "naukri"],
    )

    print("Configuration loaded successfully.")
    print(f"Enabled sources: {enabled_sources}")
    print(f"Keywords: {search_keywords}")
    print(f"Locations: {search_locations}")
    print(
        "Maximum jobs per source: "
        f"{max_jobs_per_source}"
    )
    print(f"Database: {database_path}")

    discovered_jobs: List[Any] = []
    failed_discoveries = 0
    with Database(str(database_path)) as existing_database:
        existing_urls = {
            job["job_url"]
            for job in existing_database.get_jobs()
            if job.get("job_url")
        }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=browser_headless,
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900,
            },
            locale="en-IN",
        )

        page = context.new_page()
        page.set_default_timeout(default_timeout_ms)
        page.set_default_navigation_timeout(
            navigation_timeout_ms
        )

        try:
            for source_name in enabled_sources:
                for keyword in search_keywords:
                    for location in search_locations:
                        print()
                        print("=" * 80)
                        print(
                            f"STARTING "
                            f"{source_name.upper()} JOB DISCOVERY"
                        )
                        print("=" * 80)
                        print(f"Keyword: {keyword}")
                        print(f"Location: {location}")
                        print(
                            "Maximum jobs: "
                            f"{max_jobs_per_source}"
                        )

                        try:
                            source = create_source(
                                source_name=source_name,
                                page=page,
                                keyword=keyword,
                                location=location,
                            )

                            search_arguments = {
                                "search_term": keyword,
                                "location": location,
                                "max_jobs": max_jobs_per_source,
                            }
                            if source_name.lower().strip() == "naukri":
                                search_arguments["excluded_urls"] = existing_urls
                                search_arguments["max_pages"] = max_pages_per_source

                            jobs = source.search_jobs(**search_arguments)

                            print(
                                f"{source_name.lower()} jobs extracted: "
                                f"{len(jobs)}"
                            )

                            discovered_jobs.extend(jobs)
                            existing_urls.update(
                                job.job_url
                                for job in jobs
                                if getattr(job, "job_url", "")
                            )

                        except Exception as exc:
                            failed_discoveries += 1
                            print(
                                f"Could not discover jobs from "
                                f"{source_name}: {exc}"
                            )

        finally:
            context.close()
            browser.close()
            print()
            print("Browser closed successfully.")

    print()
    print("=" * 80)
    print("NORMALIZING AND MATCHING JOBS")
    print("=" * 80)

    normalizer = JobNormalizer(
        settings=settings,
    )

    freshness_windows = settings.get("search", {}).get(
        "freshness_windows_days",
        [7, 30],
    )
    max_posted_days = max(
        int(window) for window in freshness_windows
    )

    matcher = JobMatcher(
        resume_profile=resume_profile,
        matching_rules=matching_rules,
    )

    matched_jobs: List[Dict[str, Any]] = []
    freshness_skipped = 0

    for index, raw_job in enumerate(
        discovered_jobs,
        start=1,
    ):
        try:
            normalized_job = normalizer.normalize(
                raw_job
            )

            posted_age = posted_age_days(normalized_job)
            if posted_age is not None and posted_age > max_posted_days:
                freshness_skipped += 1
                continue

            match_result = matcher.match(
                normalized_job
            )

            if not match_result.get("eligible", True):
                print(
                    f"Skipped unsuitable job: "
                    f"{normalized_job.get('title', 'Unknown title')} | "
                    f"{'; '.join(match_result.get('rejection_reasons', []))}"
                )
                continue

            # Keep the normalized job fields and match fields
            # together in one dictionary.
            final_job = {
                **normalized_job,
                **match_result,
            }

            matched_jobs.append(final_job)

            title = final_job.get(
                "title",
                "Unknown title",
            )

            company = final_job.get(
                "company",
                "Unknown company",
            )

            score = final_job.get(
                "match_score",
                0,
            )

            category = final_job.get(
                "match_category",
                "Unknown",
            )

            print(
                f"Matched {index}: "
                f"{title} | {company} | "
                f"Score: {score} | "
                f"Category: {category}"
            )

        except Exception as exc:
            print(
                f"Could not normalize or match job "
                f"{index}: {exc}"
            )

    print()
    print("=" * 80)
    print("SAVING JOBS TO DATABASE")
    print("=" * 80)

    database = Database(str(database_path))

    new_jobs = 0
    existing_jobs = 0
    failed_saves = 0
    new_leads: List[Dict[str, Any]] = []

    try:
        for job in matched_jobs:
            try:
                job_url = job.get("job_url", "")

                if not job_url:
                    print(
                        "Skipping job without URL: "
                        f"{job.get('title', 'Unknown title')}"
                    )
                    failed_saves += 1
                    continue

                already_exists = database.job_exists(
                    job_url
                )

                database.save_job(job)

                if already_exists:
                    existing_jobs += 1
                else:
                    new_jobs += 1
                    new_leads.append(job)

            except Exception as exc:
                failed_saves += 1
                print(
                    f"Could not save job "
                    f"{job.get('title', 'Unknown title')}: "
                    f"{exc}"
                )

    finally:
        database.close()

    print()
    print("=" * 80)
    print("DATABASE SUMMARY")
    print("=" * 80)
    print(f"New jobs saved: {new_jobs}")
    print(f"Existing jobs updated: {existing_jobs}")
    print(f"Failed saves: {failed_saves}")
    print(f"Total discovered: {len(discovered_jobs)}")
    print(f"Total matched: {len(matched_jobs)}")
    print(f"Failed discoveries: {failed_discoveries}")
    print(f"Skipped outside freshness window: {freshness_skipped}")

    export_directory = resolve_project_path(
        settings.get("project", {}).get(
            "export_directory",
            "data/exports",
        )
    )
    export_marker = export_directory / ".daily_exports_initialized"
    export_candidates = new_leads

    if not export_marker.exists():
        export_candidates = matched_jobs
        print(
            "Initializing daily exports with currently fresh leads."
        )

    application_settings = settings.get("application", {})
    if application_settings.get("prepare_after_search", False):
        export_candidates = prepare_new_applications(
            export_candidates,
            profile_path=PROJECT_ROOT / "config" / "application_profile.yaml",
            max_jobs=int(
                application_settings.get("max_jobs_per_run", 10)
            ),
        )

    review_page = create_application_review_page(
        export_candidates,
        export_directory,
    )
    for index, job in enumerate(export_candidates, start=1):
        job["application_progress"] = excel_review_link(
            review_page,
            index,
        )

    with Database(str(database_path)) as tracking_database:
        for job in export_candidates:
            upsert_application_record(
                tracking_database,
                job,
                review_url=job["application_progress"],
                status=job.get(
                    "application_status",
                    "Pending preparation",
                ),
                unknown_questions=job.get(
                    "unknown_questions",
                    [],
                ),
                filled_fields=job.get(
                    "filled_fields",
                    [],
                ),
            )

    export_daily_new_leads(
        jobs=export_candidates,
        export_directory=export_directory,
        freshness_windows=freshness_windows,
    )
    export_master_jobs(
        database_path=database_path,
        export_directory=export_directory,
    )
    export_marker.touch()

    print()
    print("Multi-portal job discovery pipeline completed.")


if __name__ == "__main__":
    main()
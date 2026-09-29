"""
The single job-search pipeline.

    discover -> normalize -> freshness filter -> match -> save
             -> prepare applications -> export

Run with:  python -m src.pipelines.discovery_pipeline
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

from src.application_queue import (
    create_application_review_page,
    excel_review_link,
    prepare_new_applications,
)
from src.application_tracking import upsert_application_record
from src.config import MatchingRules, Settings, load_matching_rules, load_settings, validate_model
from src.database import Database
from src.freshness import posted_age_days
from src.matching.job_matcher import JobMatcher
from src.models import Job
from src.normalizer import JobNormalizer
from src.reports.export_excel import export_daily_new_leads, export_master_jobs
from src.resume_profile import ResumeProfile, load_resume_profile

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Run context and statistics
# ----------------------------------------------------------------------


@dataclass
class RunContext:
    project_root: Path
    settings: Settings
    rules: MatchingRules
    profile: ResumeProfile

    def path(self, value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else self.project_root / candidate

    @property
    def database_path(self) -> Path:
        return self.path(self.settings.project.database_path)

    @property
    def export_directory(self) -> Path:
        return self.path(self.settings.project.export_directory)

    @property
    def application_profile_path(self) -> Path:
        return self.project_root / "config" / "application_profile.yaml"


@dataclass
class RunStats:
    discovered: int = 0
    failed_queries: int = 0
    stale: int = 0
    rejected: int = 0
    failed_matches: int = 0
    matched: int = 0
    new: int = 0
    updated: int = 0
    failed_saves: int = 0
    rejection_counts: dict[str, int] = field(default_factory=dict)

    def log_summary(self) -> None:
        logger.info("=" * 60)
        logger.info("RUN SUMMARY")
        logger.info("Discovered: %s (failed queries: %s)", self.discovered, self.failed_queries)
        logger.info("Dropped as stale: %s", self.stale)
        logger.info("Rejected by gates: %s", self.rejected)
        for reason, count in sorted(self.rejection_counts.items(), key=lambda item: -item[1]):
            logger.info("    %s: %s", reason, count)
        logger.info("Matched: %s (new %s, updated %s, failed saves %s)",
                    self.matched, self.new, self.updated, self.failed_saves)


def load_context(project_root: Path = PROJECT_ROOT) -> RunContext:
    config_directory = project_root / "config"
    return RunContext(
        project_root=project_root,
        settings=load_settings(config_directory / "settings.yaml"),
        rules=load_matching_rules(config_directory / "matching_rules.yaml"),
        profile=load_resume_profile(config_directory / "candidate_profile.yaml"),
    )


def configure_logging(context: RunContext) -> None:
    log_directory = context.path(context.settings.project.log_directory)
    log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_directory / "job_search_agent.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


# ----------------------------------------------------------------------
# Stage 1: discover (browser)
# ----------------------------------------------------------------------


def discover_jobs(
    context: RunContext,
    known_urls: set[str],
    stats: RunStats,
) -> list[Any]:
    """Run every source x keyword x location query and return raw jobs."""
    from playwright.sync_api import sync_playwright

    from src.sources import create_source

    settings = context.settings
    search = settings.search
    discovered: list[Any] = []
    seen_urls = set(known_urls)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=settings.browser.headless)
        browser_context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
            timezone_id=settings.project.timezone,
        )
        browser_context.set_default_timeout(settings.browser.default_timeout_ms)
        browser_context.set_default_navigation_timeout(settings.browser.navigation_timeout_ms)
        page = browser_context.new_page()

        try:
            for source_name in settings.sources:
                source = create_source(
                    source_name,
                    page,
                    enrich_details=search.enrich_details,
                    debug_directory=str(context.path(settings.project.debug_directory)),
                    posted_within_days=search.max_posted_days,
                )
                for keyword in search.keywords:
                    for location in search.locations:
                        logger.info("Searching %s: %s | %s", source_name, keyword, location)
                        try:
                            jobs = source.search_jobs(
                                search_term=keyword,
                                location=location,
                                max_jobs=search.max_results_per_query,
                                excluded_urls=seen_urls,
                                max_pages=search.max_pages_per_source,
                            )
                        except Exception:
                            stats.failed_queries += 1
                            logger.exception("Query failed: %s | %s | %s", source_name, keyword, location)
                            continue

                        if not jobs:
                            logger.warning(
                                "%s returned 0 jobs for '%s' in %s; check data/debug for a "
                                "blocked page or changed layout.",
                                source_name, keyword, location,
                            )

                        for job in jobs:
                            if getattr(job, "job_url", ""):
                                seen_urls.add(job.job_url)
                        discovered.extend(jobs)
                        logger.info("%s returned %s jobs", source_name, len(jobs))
        except KeyboardInterrupt:
            logger.warning("Discovery stopped by user; continuing with %s jobs.", len(discovered))
        finally:
            browser_context.close()
            browser.close()

    stats.discovered = len(discovered)
    return discovered


# ----------------------------------------------------------------------
# Stage 2: normalize, filter, match (pure)
# ----------------------------------------------------------------------


def score_jobs(
    raw_jobs: Iterable[Any],
    context: RunContext,
    stats: RunStats,
    today: date | None = None,
) -> list[Job]:
    """Normalize every job, drop stale and ineligible ones, return matches."""
    today = today or date.today()
    normalizer = JobNormalizer()
    matcher = JobMatcher(context.profile, context.rules)
    max_posted_days = context.settings.search.max_posted_days

    matched: list[Job] = []
    for raw_job in raw_jobs:
        try:
            job = normalizer.normalize(raw_job, observed_on=today)

            age = posted_age_days(job, today)
            if age is not None and age > max_posted_days:
                stats.stale += 1
                continue

            job.apply_match(matcher.match(job))
        except Exception:
            stats.failed_matches += 1
            logger.exception("Could not score job: %r", getattr(raw_job, "title", raw_job))
            continue

        if not job.eligible:
            stats.rejected += 1
            for reason in job.rejection_reasons:
                stats.rejection_counts[reason] = stats.rejection_counts.get(reason, 0) + 1
            logger.info("Rejected: %s | %s | %s", job.title, job.company, "; ".join(job.rejection_reasons))
            continue

        matched.append(job)
        logger.info("Matched: %s | %s | %s (%s)", job.title, job.company, job.match_score, job.match_category)

    stats.matched = len(matched)
    return matched


# ----------------------------------------------------------------------
# Stage 3: save
# ----------------------------------------------------------------------


def save_jobs(database: Database, jobs: Iterable[Job], stats: RunStats) -> list[Job]:
    """Upsert jobs; return the ones that were not in the database before."""
    new_leads: list[Job] = []
    for job in jobs:
        if not job.job_url:
            stats.failed_saves += 1
            continue
        try:
            inserted = database.save_job(job)
        except Exception:
            stats.failed_saves += 1
            logger.exception("Could not save job: %s", job.title)
            continue
        if inserted:
            stats.new += 1
            new_leads.append(job)
        else:
            stats.updated += 1
    return new_leads


# ----------------------------------------------------------------------
# Stage 4: prepare applications and track them
# ----------------------------------------------------------------------


def prepare_applications(context: RunContext, leads: list[Job]) -> list[dict[str, Any]]:
    """Optionally pre-fill forms for this run's new leads."""
    rows = [lead.to_dict() for lead in leads]
    application = context.settings.application
    if application.prepare_after_search and rows:
        rows = prepare_new_applications(
            rows,
            profile_path=context.application_profile_path,
            max_jobs=application.max_jobs_per_run,
        )
    return rows


def leads_for_day(
    database: Database,
    day: date,
    prepared_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Every non-rejected job first discovered on ``day``, so a second run on
    the same day adds to that day's workbook and review page instead of
    replacing them. This run's preparation results override stored ones.
    """
    prepared = {row["job_url"]: row for row in prepared_rows}
    applications = database.get_applications()
    day_prefix = day.isoformat()

    rows: list[dict[str, Any]] = []
    for job in reversed(database.get_jobs()):  # oldest first
        url = job["job_url"]
        if url in prepared:
            rows.append({**job, **prepared.pop(url)})
            continue
        if not str(job.get("discovered_at") or "").startswith(day_prefix):
            continue
        if job.get("status") == "rejected":
            continue
        row = dict(job)
        record = applications.get(url)
        if record:
            row["application_status"] = record["status"]
            row["unknown_questions"] = json.loads(record["unknown_questions"] or "[]")
            row["filled_fields"] = json.loads(record["filled_fields"] or "[]")
        rows.append(row)

    # First-run leads discovered on earlier days are still included.
    rows.extend(prepared.values())
    return rows


def track_applications(
    context: RunContext,
    database: Database,
    rows: list[dict[str, Any]],
    day: date,
) -> None:
    """Write the day's review page and one application row per lead."""
    review_page = create_application_review_page(rows, context.export_directory, day)
    for index, row in enumerate(rows, start=1):
        row["application_progress"] = excel_review_link(review_page, index)
        upsert_application_record(
            database,
            row,
            review_url=row["application_progress"],
            status=row.get("application_status", "Pending preparation"),
            unknown_questions=row.get("unknown_questions", []),
            filled_fields=row.get("filled_fields", []),
        )


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------


Discoverer = Callable[[RunContext, set[str], RunStats], list[Any]]


def run(
    context: RunContext,
    discover: Discoverer = discover_jobs,
    today: date | None = None,
) -> RunStats:
    stats = RunStats()
    run_day = today or date.today()
    export_directory = context.export_directory
    export_directory.mkdir(parents=True, exist_ok=True)

    with Database(context.database_path) as database:
        known_urls = database.get_job_urls()

        raw_jobs = discover(context, known_urls, stats)
        matched = score_jobs(raw_jobs, context, stats, today)
        new_leads = save_jobs(database, matched, stats)

        # The very first run has no history, so every current match counts
        # as a lead for the daily workbook.
        marker = export_directory / ".daily_exports_initialized"
        leads = new_leads if marker.exists() else matched

        prepared = prepare_applications(context, leads)
        rows = leads_for_day(database, run_day, prepared)
        track_applications(context, database, rows, run_day)

    export_daily_new_leads(
        rows,
        export_directory,
        run_date=run_day,
        freshness_windows=context.settings.search.freshness_windows_days,
    )
    export_master_jobs(context.database_path, export_directory)
    marker.touch()

    stats.log_summary()
    return stats


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search job portals, score jobs and export the day's leads.",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        help="Override settings.yaml sources for this run, e.g. --sources linkedin",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        help='Override settings.yaml keywords for this run, e.g. --keywords "Business Analyst"',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    arguments = parse_arguments(argv)
    context = load_context()
    # Re-validate so overrides get the same checks as settings.yaml.
    overrides: dict[str, Any] = {}
    if arguments.sources:
        overrides["sources"] = arguments.sources
    if arguments.keywords:
        overrides["search"] = {
            **context.settings.search.model_dump(),
            "keywords": arguments.keywords,
        }
    if overrides:
        context.settings = validate_model(
            Settings,
            {**context.settings.model_dump(), **overrides},
            "command-line options",
        )
    configure_logging(context)
    logger.info("Sources: %s", context.settings.sources)
    logger.info("Keywords: %s", context.settings.search.keywords)
    logger.info("Locations: %s", context.settings.search.locations)
    logger.info("Database: %s", context.database_path)
    run(context)


if __name__ == "__main__":
    main()

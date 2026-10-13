"""
LinkedIn Easy Apply in the agent's own signed-in browser profile.

One-time sign-in (you type your password; the agent never sees it):
    python -m src.apply.linkedin login

Prepare applications for top LinkedIn leads, then review and submit each
open tab yourself:
    python -m src.apply.linkedin apply [--limit 5] [--min-score 60] [--job-url URL ...]

The browser stays open until you close it. Every tab you submit is
recorded as applied in data/jobs.db. This command never submits for you;
unattended submitting lives in src.apply.auto_apply (opt-in).
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import yaml
from playwright.sync_api import BrowserContext, Page, sync_playwright

from src.apply.easy_apply import (
    ALREADY_APPLIED,
    SUBMITTED,
    READY_TO_SUBMIT,
    EasyApplyFiller,
    EasyApplyResult,
    build_answers,
)
from src.application_tracking import upsert_application_record
from src.config import EasyApplySettings
from src.database import Database
from src.pipelines.discovery_pipeline import RunContext, configure_logging, load_context

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.linkedin.com/login"
SESSION_COOKIE = "li_at"
# Any of these in the URL means LinkedIn wants a human: stop immediately.
SECURITY_CHECK_MARKERS = ("checkpoint", "challenge", "captcha", "authwall", "/login", "/uas/")

# Statuses that mean a job needs no further Easy Apply attempt.
DONE_STATUSES = (SUBMITTED, ALREADY_APPLIED, "Not Easy Apply")


class SecurityCheckError(RuntimeError):
    """LinkedIn showed a sign-in, checkpoint or CAPTCHA page."""


# ----------------------------------------------------------------------
# Browser profile
# ----------------------------------------------------------------------


@contextmanager
def signed_in_browser(context: RunContext) -> Iterator[BrowserContext]:
    settings = context.settings.easy_apply
    profile_dir = context.path(settings.browser_profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        options: dict[str, Any] = {
            "headless": False,
            "viewport": None,
            "locale": "en-IN",
            "timezone_id": context.settings.project.timezone,
        }
        try:
            browser = playwright.chromium.launch_persistent_context(
                str(profile_dir), channel=settings.browser_channel, **options
            )
        except Exception as error:
            logger.warning("Could not start %s (%s); using Playwright Chromium.", settings.browser_channel, error)
            browser = playwright.chromium.launch_persistent_context(str(profile_dir), **options)
        try:
            yield browser
        finally:
            try:
                browser.close()
            except Exception:
                pass


def is_signed_in(browser: BrowserContext) -> bool:
    return any(
        cookie["name"] == SESSION_COOKIE and cookie["value"]
        for cookie in browser.cookies("https://www.linkedin.com")
    )


def check_for_security_page(page: Page) -> None:
    url = page.url.lower()
    if any(marker in url for marker in SECURITY_CHECK_MARKERS):
        raise SecurityCheckError(
            f"LinkedIn showed a sign-in or security check ({page.url}). "
            "Stopping. Run 'python -m src.apply.linkedin login' and complete it yourself."
        )


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


def login(context: RunContext, timeout_minutes: int = 10) -> bool:
    with signed_in_browser(context) as browser:
        if is_signed_in(browser):
            print("Already signed in to LinkedIn in the agent's browser profile.")
            return True

        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(LOGIN_URL)
        print("Sign in to LinkedIn in the browser window (type your password there).")
        print(f"Waiting up to {timeout_minutes} minutes...")

        deadline = time.monotonic() + timeout_minutes * 60
        while time.monotonic() < deadline:
            try:
                signed_in = is_signed_in(browser)
                on_checkpoint = "checkpoint" in page.url
            except Exception:
                print("The browser window was closed before sign-in finished. Run the command again.")
                return False
            if signed_in and not on_checkpoint:
                print("Signed in. The session is saved in the agent's browser profile.")
                print("You can close the browser window.")
                time.sleep(2)
                return True
            time.sleep(2)

    print("Timed out before sign-in finished. Run the command again.")
    return False


CLOSED_JOB_STATUSES = ("rejected", "skipped", "applied", "interviewing", "offer")


def select_jobs(
    database: Database,
    min_score: float,
    limit: int,
    job_urls: list[str] | None = None,
    shortlisted_only: bool = False,
) -> list[dict[str, Any]]:
    jobs = {job["job_url"]: job for job in database.get_jobs()}
    if job_urls:
        return [jobs.get(url, {"job_url": url, "title": "", "company": ""}) for url in job_urls]

    applications = database.get_applications()
    candidates = [
        job
        for job in jobs.values()
        if job.get("source") == "linkedin"
        and job.get("status") not in CLOSED_JOB_STATUSES
        and (not shortlisted_only or job.get("status") == "shortlisted")
        and (job.get("match_score") or 0) >= min_score
        and applications.get(job["job_url"], {}).get("status") not in DONE_STATUSES
    ]
    candidates.sort(key=lambda job: -(job.get("match_score") or 0))
    return candidates[:limit]


def record(database: Database, job: dict[str, Any], result: EasyApplyResult) -> None:
    upsert_application_record(
        database,
        job,
        review_url=job["job_url"],
        status=result.status,
        unknown_questions=result.unknown_questions,
        filled_fields=result.filled_fields,
    )
    if result.status in (SUBMITTED, ALREADY_APPLIED):
        database.update_job_status(job["job_url"], "applied", notes=f"LinkedIn Easy Apply: {result.status}")


def apply(
    context: RunContext,
    limit: int | None = None,
    min_score: float | None = None,
    job_urls: list[str] | None = None,
) -> None:
    settings: EasyApplySettings = context.settings.easy_apply
    profile = yaml.safe_load(context.application_profile_path.read_text(encoding="utf-8")) or {}
    answers = build_answers(profile)

    with Database(context.database_path) as database:
        jobs = select_jobs(
            database,
            min_score=settings.min_match_score if min_score is None else min_score,
            limit=limit or settings.max_jobs_per_run,
            job_urls=job_urls,
        )
        if not jobs:
            print("No LinkedIn jobs to prepare. Run a LinkedIn search first or lower --min-score.")
            return

        with signed_in_browser(context) as browser:
            if not is_signed_in(browser):
                print("Not signed in. Run: python -m src.apply.linkedin login")
                return

            open_tabs: dict[str, tuple[Page, dict[str, Any]]] = {}
            try:
                for index, job in enumerate(jobs):
                    if index:
                        # Human-like pacing between applications.
                        time.sleep(settings.seconds_between_jobs * random.uniform(0.8, 1.4))

                    page = browser.new_page()
                    logger.info("Preparing %s | %s (%s)", job.get("title"), job.get("company"), job["job_url"])
                    page.goto(job["job_url"], wait_until="domcontentloaded")
                    page.wait_for_timeout(3_000)
                    check_for_security_page(page)

                    try:
                        result = EasyApplyFiller(page, answers, settings.max_steps_per_application).prepare()
                    except Exception as error:
                        logger.exception("Easy Apply failed for %s", job["job_url"])
                        result = EasyApplyResult(f"Failed: {error}"[:200])

                    record(database, job, result)
                    logger.info(
                        "%s | filled %s | questions for you: %s",
                        result.status,
                        len(result.filled_fields),
                        "; ".join(result.unknown_questions) or "none",
                    )
                    if result.needs_candidate:
                        open_tabs[job["job_url"]] = (page, job)
                    else:
                        page.close()
            except SecurityCheckError as error:
                print(str(error))

            if not open_tabs:
                print("No applications are waiting for you.")
                return

            print()
            print(f"{len(open_tabs)} application(s) are open in the browser.")
            print("Review each tab, answer anything left blank, and click Submit yourself.")
            print("Close the browser window when you are done.")
            watch_for_submissions(browser, database, open_tabs)


def auto_apply_jobs(
    context: RunContext,
    database: Database,
    browser: BrowserContext,
    jobs: list[dict[str, Any]],
    answers: dict[str, str],
    budget: int,
) -> list[tuple[dict[str, Any], EasyApplyResult]]:
    """
    Unattended Easy Apply: fill each form and submit it only when every
    required question was answered from approved answers. Stops at the
    first sign-in, checkpoint or CAPTCHA page. Never waits for a person.
    """
    settings = context.settings.easy_apply
    results: list[tuple[dict[str, Any], EasyApplyResult]] = []
    submitted = 0
    for index, job in enumerate(jobs):
        if submitted >= budget:
            logger.info("LinkedIn auto-apply: daily cap reached")
            break
        if index:
            time.sleep(settings.seconds_between_jobs * random.uniform(0.8, 1.4))
        page = browser.new_page()
        try:
            page.goto(job["job_url"], wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)
            check_for_security_page(page)
            filler = EasyApplyFiller(page, answers, settings.max_steps_per_application)
            result = filler.prepare()
            if result.status == READY_TO_SUBMIT and not result.unknown_questions:
                if filler.submit():
                    result.status = SUBMITTED
                    submitted += 1
                else:
                    check_for_security_page(page)
                    result.status = "Submit not confirmed (Easy Apply)"
        except SecurityCheckError:
            page.close()
            raise
        except Exception as error:
            logger.exception("Auto-apply failed for %s", job["job_url"])
            result = EasyApplyResult(f"Failed: {error}"[:200])
        record(database, job, result)
        logger.info("LinkedIn auto-apply | %s | %s | %s | questions: %s", result.status,
                    job.get("title"), job.get("company"), "; ".join(result.unknown_questions) or "none")
        results.append((job, result))
        page.close()
    return results


def watch_for_submissions(
    browser: BrowserContext,
    database: Database,
    open_tabs: dict[str, tuple[Page, dict[str, Any]]],
) -> None:
    """Mark jobs applied when LinkedIn confirms, until the browser closes."""
    pending = dict(open_tabs)
    while pending:
        try:
            browser.pages  # raises once the window is closed
            time.sleep(2)
        except Exception:
            break
        for url, (page, job) in list(pending.items()):
            if page.is_closed():
                pending.pop(url)
                continue
            if EasyApplyFiller.application_sent(page):
                record(database, job, EasyApplyResult(SUBMITTED))
                logger.info("Recorded as applied: %s | %s", job.get("title"), job.get("company"))
                pending.pop(url)
        if not browser.pages:
            break

    submitted = [
        url for url in open_tabs if database.get_applications().get(url, {}).get("status") == SUBMITTED
    ]
    print(f"Submitted and recorded: {len(submitted)} of {len(open_tabs)}.")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LinkedIn Easy Apply (you submit).")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="Sign in once in the agent's browser profile.")
    apply_parser = commands.add_parser("apply", help="Prepare Easy Apply forms for top LinkedIn leads.")
    apply_parser.add_argument("--limit", type=int, help="Maximum jobs this run (default from settings).")
    apply_parser.add_argument("--min-score", type=float, help="Minimum match score (default from settings).")
    apply_parser.add_argument("--job-url", nargs="+", help="Prepare these LinkedIn job URLs instead.")
    arguments = parser.parse_args(argv)

    context = load_context()
    configure_logging(context)

    if arguments.command == "login":
        sys.exit(0 if login(context) else 1)
    apply(context, arguments.limit, arguments.min_score, arguments.job_url)


if __name__ == "__main__":
    main()

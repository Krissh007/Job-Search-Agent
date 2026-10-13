"""
Unattended auto-apply on LinkedIn (Easy Apply) and Naukri.

    python -m src.apply.auto_apply              # uses auto_apply in settings.yaml
    python -m src.apply.auto_apply --dry-run    # list what would be applied to
    python -m src.apply.auto_apply --limit 3

Safeguards (all in settings.yaml -> auto_apply):
- Off unless ``enabled: true``.
- By default only jobs marked "shortlisted" (by Claude's daily review in the
  Job Application project, or by you) and scoring >= min_match_score.
- Submits a form only when every required question was answered from
  config/application_profile.yaml. Otherwise nothing is submitted and the
  questions go to project_sync/open_questions.md for you to answer once.
- At most ``daily_cap`` submissions per day across portals, randomised
  pauses between jobs, and an immediate stop on any sign-in, OTP,
  checkpoint or CAPTCHA page.

Automating a signed-in LinkedIn or Naukri account is against both sites'
terms and can get the account restricted; the cap and pacing reduce, not
remove, that risk.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from typing import Any

import yaml

from src.apply import linkedin, naukri
from src.apply.easy_apply import build_answers
from src.database import Database
from src.pipelines.discovery_pipeline import RunContext, configure_logging, load_context

logger = logging.getLogger(__name__)

CLOSED_JOB_STATUSES = ("rejected", "skipped", "applied", "interviewing", "offer")


def submitted_today(database: Database, today: date | None = None) -> int:
    day = (today or date.today()).isoformat()
    row = database.connection.execute(
        "SELECT COUNT(*) FROM jobs WHERE status = 'applied' AND applied_at LIKE ? "
        "AND (notes LIKE 'LinkedIn Easy Apply%' OR notes LIKE 'Naukri apply%')",
        (f"{day}%",),
    ).fetchone()
    return int(row[0])


def select_jobs(context: RunContext, database: Database, source: str) -> list[dict[str, Any]]:
    settings = context.settings.auto_apply
    applications = database.get_applications()
    done = linkedin.DONE_STATUSES if source == "linkedin" else naukri.DONE_STATUSES
    jobs = [
        job for job in database.get_jobs(source=source)
        if job.get("status") not in CLOSED_JOB_STATUSES
        and (not settings.shortlisted_only or job.get("status") == "shortlisted")
        and (job.get("match_score") or 0) >= settings.min_match_score
        and applications.get(job["job_url"], {}).get("status") not in done
    ]
    jobs.sort(key=lambda job: -(job.get("match_score") or 0))
    return jobs


def run(context: RunContext, dry_run: bool = False, limit: int | None = None) -> dict[str, int]:
    settings = context.settings.auto_apply
    summary = {"submitted": 0, "needs_answers": 0, "other": 0}
    if not settings.enabled and not dry_run:
        logger.info("Auto-apply is disabled (auto_apply.enabled in settings.yaml)")
        return summary

    profile = yaml.safe_load(context.application_profile_path.read_text(encoding="utf-8")) or {}
    answers = build_answers(profile)

    with Database(context.database_path) as database:
        budget = settings.daily_cap - submitted_today(database)
        if limit is not None:
            budget = min(budget, limit)
        queue = {source: select_jobs(context, database, source) for source in settings.sources}
        logger.info("Auto-apply: budget %s today; queued %s", budget,
                    {source: len(jobs) for source, jobs in queue.items()})

        if dry_run:
            for source, jobs in queue.items():
                for job in jobs:
                    print(f"[{source}] {job.get('match_score')} | {job.get('title')} | {job.get('company')} | {job['job_url']}")
            return summary
        if budget <= 0 or not any(queue.values()):
            return summary

        with linkedin.signed_in_browser(context) as browser:
            for source, jobs in queue.items():
                if budget <= 0 or not jobs:
                    continue
                module = linkedin if source == "linkedin" else naukri
                if not module.is_signed_in(browser):
                    logger.warning("Not signed in to %s; run: python -m src.apply.%s login", source, source)
                    continue
                try:
                    results = module.auto_apply_jobs(context, database, browser, jobs, answers, budget)
                except (linkedin.SecurityCheckError, naukri.NaukriSecurityError) as error:
                    logger.warning("%s", error)
                    continue
                for _, result in results:
                    if result.status == "Submitted":
                        summary["submitted"] += 1
                        budget -= 1
                    elif result.unknown_questions:
                        summary["needs_answers"] += 1
                    else:
                        summary["other"] += 1

    logger.info("Auto-apply summary: %s", summary)
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Only list the jobs that would be applied to")
    parser.add_argument("--limit", type=int, help="At most this many submissions this run")
    args = parser.parse_args(argv)
    context = load_context()
    configure_logging(context)
    print(run(context, dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

from src.config_manager import ConfigManager
from src.database import Database
from src.matching.job_matcher import JobMatcher
from src.reports.export_excel import export_master_jobs
from src.reports.export_excel import export_daily_new_leads
from src.resume_profile import load_resume_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "jobs.db"
EXPORT_DIRECTORY = PROJECT_ROOT / "data" / "exports"


def main() -> None:
    profile = load_resume_profile(
        PROJECT_ROOT / "config" / "candidate_profile.yaml"
    )
    rules = ConfigManager(
        PROJECT_ROOT / "config" / "matching_rules.yaml"
    ).all()
    matcher = JobMatcher(profile, rules)
    rejected = 0
    retained = 0
    retained_jobs = []

    with Database(DATABASE_PATH) as database:
        jobs = database.get_jobs()
        for job in jobs:
            result = matcher.match(job)
            job.update(result)
            if result.get("eligible", True):
                job["status"] = (
                    "new" if job.get("status") == "rejected" else job.get(
                        "status",
                        "new",
                    )
                )
                retained += 1
                retained_jobs.append(job)
            else:
                job["status"] = "rejected"
                job["notes"] = (
                    "Rejected by quality filters: "
                    + "; ".join(result.get("rejection_reasons", []))
                )
                rejected += 1
            database.save_job(job)
            database.connection.execute(
                """
                UPDATE applications
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE job_url = ?
                """,
                (
                    "Rejected by quality filters"
                    if job["status"] == "rejected"
                    else "Ready for review",
                    job.get("job_url", ""),
                ),
            )
        database.connection.commit()

    export_master_jobs(DATABASE_PATH, EXPORT_DIRECTORY)
    for window in (7, 30):
        export_daily_new_leads(
            retained_jobs,
            EXPORT_DIRECTORY,
            freshness_windows=(window,),
        )
    print(f"Retained jobs: {retained}")
    print(f"Rejected jobs: {rejected}")
    print("Rejected jobs remain in SQLite history but are not actionable.")


if __name__ == "__main__":
    main()

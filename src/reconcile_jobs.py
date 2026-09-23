"""
Re-score every stored job with the current profile and rules.

Run after editing candidate_profile.yaml or matching_rules.yaml:
    python -m src.reconcile_jobs
"""

from __future__ import annotations

from src.database import Database
from src.matching.job_matcher import JobMatcher
from src.pipelines.discovery_pipeline import load_context
from src.reports.export_excel import export_master_jobs

REJECTED_NOTE_PREFIX = "Rejected by quality filters: "


def main() -> None:
    context = load_context()
    matcher = JobMatcher(context.profile, context.rules)
    rejected = 0
    retained = 0

    with Database(context.database_path) as database:
        for job in database.get_jobs():
            result = matcher.match(job)
            job_url = job["job_url"]
            database.update_job_match(
                job_url=job_url,
                match_score=result["match_score"],
                match_category=result["match_category"],
                match_reasons=result["match_reasons"],
                missing_keywords=result["missing_keywords"],
                rejection_reasons=result["rejection_reasons"],
                evidence_count=result["evidence_count"],
            )

            status = job.get("status") or "new"
            if not result["eligible"]:
                rejected += 1
                # Never overwrite a decision the candidate already made.
                if status in ("new", "rejected"):
                    database.update_job_status(
                        job_url,
                        "rejected",
                        REJECTED_NOTE_PREFIX + "; ".join(result["rejection_reasons"]),
                    )
            else:
                retained += 1
                if status == "rejected":
                    database.update_job_status(job_url, "new", "")

    export_master_jobs(context.database_path, context.export_directory)
    print(f"Retained jobs: {retained}")
    print(f"Rejected jobs: {rejected}")
    print("Rejected jobs remain in SQLite history but are not exported.")


if __name__ == "__main__":
    main()

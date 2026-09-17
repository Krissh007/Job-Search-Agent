from __future__ import annotations

from pathlib import Path

from src.application_queue import (
    create_application_review_page,
    excel_review_link,
    prepare_new_applications,
)
from src.application_tracking import upsert_application_record
from src.database import Database
from src.reports.export_excel import export_master_jobs

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "jobs.db"
EXPORT_DIRECTORY = PROJECT_ROOT / "data" / "exports"
PROFILE_PATH = PROJECT_ROOT / "config" / "application_profile.yaml"


def main() -> None:
    with Database(DATABASE_PATH) as database:
        jobs = [
            job
            for job in database.get_jobs()
            if job.get("status") != "rejected"
        ]

    prepared_jobs = prepare_new_applications(
        jobs,
        profile_path=PROFILE_PATH,
        max_jobs=0,
    )
    review_page = create_application_review_page(
        prepared_jobs,
        EXPORT_DIRECTORY,
    )

    with Database(DATABASE_PATH) as database:
        for index, job in enumerate(prepared_jobs, start=1):
            review_link = excel_review_link(review_page, index)
            job["application_progress"] = review_link
            upsert_application_record(
                database,
                job,
                review_url=review_link,
                status=job.get(
                    "application_status",
                    "Pending preparation",
                ),
                unknown_questions=job.get("unknown_questions", []),
                filled_fields=job.get("filled_fields", []),
            )

    export_master_jobs(DATABASE_PATH, EXPORT_DIRECTORY)
    print(f"Prepared applications: {len(prepared_jobs)}")
    print(f"Review page: {review_page}")
    print("No applications were submitted.")


if __name__ == "__main__":
    main()

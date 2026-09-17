from pathlib import Path

from src.database import Database
from src.models import Job


def main() -> None:
    """Test saving a Job object directly into SQLite."""

    project_root = Path(__file__).resolve().parent.parent
    database_path = project_root / "data" / "test_model_jobs.db"

    database = Database(database_path)

    job = Job(
        job_url="https://example.com/jobs/model-test-001",
        source="test",
        title="AI Business Analyst",
        company="Model Test Company",
        location="Hyderabad",
        posted_date="2026-09-16",
        description="Testing Job model integration with SQLite.",
        match_score=88.0,
        match_category="Strong",
        match_reasons="Relevant business analysis and AI experience",
        status="new",
        notes="Created during model-database integration testing",
    )

    print("Saving Job object...")
    database.save_job(job)

    print("\nRetrieved job:")
    jobs = database.get_jobs()

    for saved_job in jobs:
        if saved_job["job_url"] == job.job_url:
            print(f"Title: {saved_job['title']}")
            print(f"Company: {saved_job['company']}")
            print(f"Location: {saved_job['location']}")
            print(f"Score: {saved_job['match_score']}")
            print(f"Status: {saved_job['status']}")

    print("\nModel-database integration test completed successfully.")


if __name__ == "__main__":
    main()
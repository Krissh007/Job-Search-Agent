from src.database import Database


def test_database_creation_and_updates(tmp_path):
    database_path = tmp_path / "test_jobs.db"

    database = Database(database_path)

    sample_job = {
        "job_url": "https://example.com/jobs/sample-ai-business-analyst",
        "source": "test",
        "title": "AI Business Analyst",
        "company": "Example Company",
        "location": "Hyderabad",
        "posted_date": "2026-09-16",
        "description": "Sample job used to test the database.",
        "match_score": 82.5,
        "match_category": "Strong",
        "match_reasons": "Relevant business analysis and AI experience",
        "missing_keywords": "",
        "status": "new",
        "notes": "Database test record",
    }

    database.save_job(sample_job)

    jobs = database.get_jobs()

    assert len(jobs) == 1
    assert jobs[0]["title"] == "AI Business Analyst"
    assert jobs[0]["status"] == "new"

    database.update_job_status(
        job_url=sample_job["job_url"],
        status="reviewed",
        notes="Reviewed during database testing",
    )

    reviewed_jobs = database.get_jobs(status="reviewed")

    assert len(reviewed_jobs) == 1
    assert reviewed_jobs[0]["status"] == "reviewed"
    assert reviewed_jobs[0]["notes"] == "Reviewed during database testing"


def test_update_job_match(tmp_path):
    database_path = tmp_path / "test_match.db"

    database = Database(database_path)

    job = {
        "job_url": "https://example.com/jobs/match-test",
        "source": "test",
        "title": "Business Analyst",
        "company": "Example Company",
        "location": "Hyderabad",
    }

    database.save_job(job)

    database.update_job_match(
        job_url=job["job_url"],
        match_score=91.0,
        match_category="Strong",
        match_reasons="Role and SQL skills matched",
        missing_keywords="Power BI",
    )

    jobs = database.get_jobs()

    assert len(jobs) == 1
    assert jobs[0]["match_score"] == 91.0
    assert jobs[0]["match_category"] == "Strong"
    assert jobs[0]["match_reasons"] == "Role and SQL skills matched"
    assert jobs[0]["missing_keywords"] == "Power BI"
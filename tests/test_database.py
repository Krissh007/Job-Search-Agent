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

def test_job_object_round_trip(tmp_path):
    from src.models import Job

    database = Database(tmp_path / "jobs.db")
    job = Job(
        job_url="https://example.com/jobs/round-trip",
        title="Business Analyst",
        experience="3-5 Yrs",
        experience_min=3,
        experience_max=5,
        salary="8-12 Lacs PA",
        posted_on="2026-09-21",
        match_reasons=["SQL", "UAT"],
        rejection_reasons=[],
        evidence_count=2,
    )
    assert database.save_job(job) is True
    assert database.save_job(job) is False

    saved = database.get_jobs()[0]
    assert saved["experience_min"] == 3
    assert saved["salary"] == "8-12 Lacs PA"
    assert saved["posted_on"] == "2026-09-21"
    assert saved["match_reasons"] == ["SQL", "UAT"]


def test_rediscovery_keeps_candidate_status(tmp_path):
    database = Database(tmp_path / "jobs.db")
    job = {"job_url": "https://example.com/jobs/applied", "title": "BA"}
    database.save_job(job)
    database.update_job_status(job["job_url"], "applied", "Applied on portal")

    database.save_job({**job, "title": "BA (updated)"})

    saved = database.get_jobs()[0]
    assert saved["title"] == "BA (updated)"
    assert saved["status"] == "applied"
    assert saved["notes"] == "Applied on portal"
    assert saved["applied_at"]


def test_old_database_is_migrated_and_backfilled(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT NOT NULL UNIQUE, source TEXT, title TEXT,
            company TEXT, location TEXT, posted_date TEXT, description TEXT,
            match_score REAL, match_category TEXT, match_reasons TEXT,
            missing_keywords TEXT, status TEXT DEFAULT 'new', notes TEXT,
            discovered_at TEXT, updated_at TEXT, applied_at TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO jobs (job_url, title, posted_date, discovered_at) VALUES (?, ?, ?, ?)",
        ("https://example.com/jobs/old", "BA", "3 days ago", "2026-09-17T08:00:00"),
    )
    connection.commit()
    connection.close()

    with Database(path) as database:
        saved = database.get_jobs()[0]

    # Resolved against the discovery day, not today.
    assert saved["posted_on"] == "2026-09-14"

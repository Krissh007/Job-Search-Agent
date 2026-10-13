from datetime import date, datetime
from pathlib import Path

from src.apply import auto_apply
from src.database import Database
from src.pipelines.discovery_pipeline import load_context


def _job(url, source, score, status):
    return {"job_url": url, "title": "BA", "company": "Acme", "source": source,
            "match_score": score, "status": status, "description": "x"}


def test_selects_only_shortlisted_scoring_jobs(tmp_path):
    context = load_context(Path(__file__).resolve().parents[1])
    with Database(tmp_path / "jobs.db") as db:
        db.save_job(_job("https://l/1", "linkedin", 80, "shortlisted"))
        db.save_job(_job("https://l/2", "linkedin", 90, "new"))
        db.save_job(_job("https://l/3", "linkedin", 50, "shortlisted"))
        db.save_job(_job("https://n/1", "naukri", 70, "shortlisted"))
        db.update_job_status("https://l/1", "shortlisted")
        db.update_job_status("https://l/3", "shortlisted")
        db.update_job_status("https://n/1", "shortlisted")
        assert [j["job_url"] for j in auto_apply.select_jobs(context, db, "linkedin")] == ["https://l/1"]
        assert [j["job_url"] for j in auto_apply.select_jobs(context, db, "naukri")] == ["https://n/1"]


def test_daily_cap_counts_only_todays_auto_submissions(tmp_path):
    with Database(tmp_path / "jobs.db") as db:
        db.save_job(_job("https://l/1", "linkedin", 80, "new"))
        db.save_job(_job("https://n/1", "naukri", 80, "new"))
        db.save_job(_job("https://x/1", "naukri", 80, "new"))
        db.update_job_status("https://l/1", "applied", "LinkedIn Easy Apply: Submitted")
        db.update_job_status("https://n/1", "applied", "Naukri apply: Submitted")
        db.update_job_status("https://x/1", "applied", "applied by hand")
        assert auto_apply.submitted_today(db) == 2
        assert auto_apply.submitted_today(db, date(2000, 1, 1)) == 0

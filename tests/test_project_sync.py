import csv
import json
from datetime import datetime

from src.database import Database
from src.project_sync import export_snapshot, import_updates, is_real_question


def _job(url, score, status="new"):
    return {"job_url": url, "title": "Business Analyst", "company": "Acme", "location": "Hyderabad",
            "description": "Gather requirements " * 30, "match_score": score,
            "match_category": "Good", "status": status, "source": "naukri"}


def test_junk_fields_are_not_questions():
    for junk in ["trk", "loginCsrfParam", "session_key", "geoId", "First Name First Name firstName"]:
        assert not is_real_question(junk)
    assert is_real_question("How many years of experience do you have with SQL?")


def test_export_then_import_round_trip(tmp_path):
    out = tmp_path / "project_sync"
    with Database(tmp_path / "jobs.db") as db:
        db.save_job(_job("https://a", 80))
        db.save_job(_job("https://b", 30))
        db.connection.execute(
            "INSERT INTO applications (job_url, status, unknown_questions) VALUES (?,?,?)",
            ("https://a", "Answers needed", json.dumps(["trk", "Notice period in days?"])))
        db.connection.commit()

        counts = export_snapshot(db, out, datetime(2026, 10, 5))
        assert counts == {"review": 1, "tracked": 0, "questions": 1}
        rows = list(csv.DictReader((out / "jobs_for_review.csv").open(encoding="utf-8-sig")))
        assert [r["job_url"] for r in rows] == ["https://a"]
        assert "Notice period" in (out / "open_questions.md").read_text(encoding="utf-8")
        assert "trk" not in (out / "open_questions.md").read_text(encoding="utf-8")

        (out / "inbox" / "status_updates.csv").write_text(
            "job_url,status,notes\nhttps://a,applied,via Naukri\nhttps://zzz,applied,\nhttps://b,bogus,\n",
            encoding="utf-8")
        result = import_updates(db, out, datetime(2026, 10, 5, 9))
        assert result == {"applied": 1, "skipped": 2}
        assert not (out / "inbox" / "status_updates.csv").exists()
        assert (out / "inbox" / "processed" / "status_updates_20261005_090000.csv").exists()

        job = {j["job_url"]: j for j in db.get_jobs()}["https://a"]
        assert job["status"] == "applied" and job["notes"] == "via Naukri" and job["applied_at"]

        export_snapshot(db, out)
        tracker = list(csv.DictReader((out / "tracker.csv").open(encoding="utf-8-sig")))
        assert [r["job_url"] for r in tracker] == ["https://a"]

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.freshness import derive_posted_on
from src.models import Job

# Column name -> SQL type for the jobs table, in table order. New columns
# added here are created on existing databases by ``_migrate``.
JOB_COLUMNS: dict[str, str] = {
    "job_url": "TEXT NOT NULL UNIQUE",
    "source": "TEXT",
    "title": "TEXT",
    "company": "TEXT",
    "location": "TEXT",
    "salary": "TEXT",
    "job_type": "TEXT",
    "experience": "TEXT",
    "experience_min": "INTEGER",
    "experience_max": "INTEGER",
    "posted_date": "TEXT",
    "posted_on": "TEXT",
    "description": "TEXT",
    "search_term": "TEXT",
    "search_location": "TEXT",
    "match_score": "REAL",
    "match_category": "TEXT",
    "match_reasons": "TEXT",
    "missing_keywords": "TEXT",
    "rejection_reasons": "TEXT",
    "evidence_count": "INTEGER",
    "status": "TEXT DEFAULT 'new'",
    "notes": "TEXT",
    "discovered_at": "TEXT",
    "updated_at": "TEXT",
    "applied_at": "TEXT",
}

JSON_COLUMNS = ("match_reasons", "missing_keywords", "rejection_reasons")

# Columns a re-discovery or re-score may overwrite. Tracking fields
# (status, notes, applied_at) and discovered_at are owned by the user or by
# the first sighting and are only changed through explicit updates.
UPSERT_UPDATABLE = [
    column
    for column in JOB_COLUMNS
    if column not in ("job_url", "status", "notes", "discovered_at", "applied_at")
]


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

        if not self.db_path.is_absolute():
            self.db_path = Path.cwd() / self.db_path

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.row_factory = sqlite3.Row

        self.create_tables()
        self._migrate()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def create_tables(self) -> None:
        column_sql = ",\n".join(
            f"{name} {sql_type}" for name, sql_type in JOB_COLUMNS.items()
        )
        self.connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {column_sql}
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)"
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                job_url TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                review_url TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                unknown_questions TEXT,
                filled_fields TEXT,
                updated_at TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tailored_documents (
                job_url TEXT PRIMARY KEY,
                resume_path TEXT NOT NULL,
                cover_letter_path TEXT NOT NULL,
                report_path TEXT,
                keyword_coverage REAL,
                match_score REAL,
                model TEXT,
                created_at TEXT
            )
            """
        )
        self.connection.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was created."""
        existing = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(jobs)")
        }
        added = []
        for name, sql_type in JOB_COLUMNS.items():
            if name in existing:
                continue
            # SQLite cannot add UNIQUE / NOT NULL columns; none of the
            # migrated columns need them.
            self.connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}")
            added.append(name)

        if "posted_on" in added or "experience" in added:
            self._backfill()
        self.connection.commit()

    def _backfill(self) -> None:
        """
        Derive posted_on and experience for rows saved by older versions.
        Relative text such as '3 days ago' is resolved against the day the
        row was discovered, not today.
        """
        from src.normalizer import parse_experience_range

        rows = self.connection.execute(
            "SELECT id, posted_date, discovered_at, job_type, experience, posted_on FROM jobs"
        ).fetchall()
        for row in rows:
            updates: dict[str, Any] = {}

            if not row["posted_on"]:
                try:
                    observed = datetime.fromisoformat(row["discovered_at"]).date()
                except (TypeError, ValueError):
                    observed = date.today()
                posted_on = derive_posted_on({"posted_date": row["posted_date"]}, observed)
                if posted_on:
                    updates["posted_on"] = posted_on

            experience_text = row["experience"] or row["job_type"] or ""
            low, high = parse_experience_range(experience_text)
            if low is not None or high is not None:
                updates.update(
                    experience=experience_text,
                    experience_min=low,
                    experience_max=high,
                )

            if updates:
                assignments = ", ".join(f"{key} = ?" for key in updates)
                self.connection.execute(
                    f"UPDATE jobs SET {assignments} WHERE id = ?",
                    [*updates.values(), row["id"]],
                )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, (list, dict, tuple)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, bool):
            return int(value)
        return value

    @staticmethod
    def _deserialize_value(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
        return value

    @staticmethod
    def _job_values(job: Job | Dict[str, Any]) -> Dict[str, Any]:
        data = job.to_dict() if isinstance(job, Job) else dict(job)
        if not data.get("job_url") and data.get("url"):
            data["job_url"] = data["url"]
        return data

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def save_job(self, job: Job | Dict[str, Any]) -> bool:
        """
        Insert a new job or update an existing one.

        Returns True if a new job was inserted, False if one was updated.
        """
        data = self._job_values(job)
        job_url = data.get("job_url")
        if not job_url:
            raise ValueError("Cannot save a job without a job URL.")

        now = datetime.now().isoformat(timespec="seconds")
        values = {
            column: self._serialize_value(data.get(column))
            for column in JOB_COLUMNS
        }
        values["status"] = data.get("status") or "new"
        values["notes"] = data.get("notes") or ""
        values["discovered_at"] = data.get("discovered_at") or now
        values["updated_at"] = now

        existing = self.job_exists(job_url)

        columns = list(JOB_COLUMNS)
        placeholders = ", ".join(f":{column}" for column in columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in UPSERT_UPDATABLE)

        self.connection.execute(
            f"""
            INSERT INTO jobs ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(job_url) DO UPDATE SET {updates}
            """,
            values,
        )
        self.connection.commit()
        return not existing

    def get_jobs(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM jobs WHERE 1=1"
        parameters: List[Any] = []

        if status is not None:
            query += " AND status = ?"
            parameters.append(status)

        if source is not None:
            query += " AND source = ?"
            parameters.append(source)

        query += " ORDER BY discovered_at DESC"

        jobs: List[Dict[str, Any]] = []
        for row in self.connection.execute(query, parameters).fetchall():
            item = dict(row)
            for column in JSON_COLUMNS:
                item[column] = self._deserialize_value(item.get(column))
            jobs.append(item)
        return jobs

    def get_job_urls(self) -> set[str]:
        return {
            row["job_url"]
            for row in self.connection.execute("SELECT job_url FROM jobs")
            if row["job_url"]
        }

    def job_exists(self, job_url: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM jobs WHERE job_url = ? LIMIT 1",
            (job_url,),
        ).fetchone()
        return row is not None

    def update_job_status(
        self,
        job_url: str,
        status: str,
        notes: Optional[str] = None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        applied_at = now if status == "applied" else None

        self.connection.execute(
            """
            UPDATE jobs
            SET status = ?,
                notes = COALESCE(?, notes),
                applied_at = COALESCE(?, applied_at),
                updated_at = ?
            WHERE job_url = ?
            """,
            (status, notes, applied_at, now, job_url),
        )
        self.connection.commit()

    def update_job_match(
        self,
        job_url: str,
        match_score: float,
        match_category: str,
        match_reasons: Optional[List[str]] = None,
        missing_keywords: Optional[List[str]] = None,
        rejection_reasons: Optional[List[str]] = None,
        evidence_count: Optional[int] = None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")

        self.connection.execute(
            """
            UPDATE jobs
            SET match_score = ?,
                match_category = ?,
                match_reasons = ?,
                missing_keywords = ?,
                rejection_reasons = ?,
                evidence_count = COALESCE(?, evidence_count),
                updated_at = ?
            WHERE job_url = ?
            """,
            (
                match_score,
                match_category,
                self._serialize_value(match_reasons or []),
                self._serialize_value(missing_keywords or []),
                self._serialize_value(rejection_reasons or []),
                evidence_count,
                now,
                job_url,
            ),
        )
        self.connection.commit()

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------

    def get_applications(self) -> Dict[str, Dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM applications").fetchall()
        return {row["job_url"]: dict(row) for row in rows}

    # ------------------------------------------------------------------
    # Tailored resumes and cover letters
    # ------------------------------------------------------------------

    def get_tailored_documents(self) -> Dict[str, Dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM tailored_documents").fetchall()
        return {row["job_url"]: dict(row) for row in rows}

    def save_tailored_documents(
        self,
        job_url: str,
        resume_path: str,
        cover_letter_path: str,
        report_path: str = "",
        keyword_coverage: Optional[float] = None,
        match_score: Optional[float] = None,
        model: str = "",
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """
            INSERT INTO tailored_documents (
                job_url, resume_path, cover_letter_path, report_path,
                keyword_coverage, match_score, model, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_url) DO UPDATE SET
                resume_path = excluded.resume_path,
                cover_letter_path = excluded.cover_letter_path,
                report_path = excluded.report_path,
                keyword_coverage = excluded.keyword_coverage,
                match_score = excluded.match_score,
                model = excluded.model,
                created_at = excluded.created_at
            """,
            (job_url, resume_path, cover_letter_path, report_path,
             keyword_coverage, match_score, model, now),
        )
        self.connection.commit()

    def delete_tailored_documents(self, job_url: str) -> None:
        self.connection.execute("DELETE FROM tailored_documents WHERE job_url = ?", (job_url,))
        self.connection.commit()

    def close(self) -> None:
        if self.connection:
            self.connection.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

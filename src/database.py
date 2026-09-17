from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import Job


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

        if not self.db_path.is_absolute():
            self.db_path = Path.cwd() / self.db_path

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.row_factory = sqlite3.Row

        self.create_tables()

    def create_tables(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_url TEXT NOT NULL UNIQUE,
                source TEXT,
                title TEXT,
                company TEXT,
                location TEXT,
                posted_date TEXT,
                description TEXT,
                match_score REAL,
                match_category TEXT,
                match_reasons TEXT,
                missing_keywords TEXT,
                status TEXT DEFAULT 'new',
                notes TEXT,
                discovered_at TEXT,
                updated_at TEXT,
                applied_at TEXT
            )
            """
        )

        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_status
            ON jobs(status)
            """
        )

        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_source
            ON jobs(source)
            """
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

        self.connection.commit()

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

        value = value.strip()

        if value.startswith("[") or value.startswith("{"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value

        return value

    @staticmethod
    def _get_job_value(
        job: Job | Dict[str, Any] | Any,
        field_name: str,
        default: Any = None,
    ) -> Any:
        """
        Safely retrieve a field from a Job object or dictionary.
        """
        if isinstance(job, dict):
            return job.get(field_name, default)

        return getattr(job, field_name, default)

    def save_job(self, job: Job | Dict[str, Any] | Any) -> bool:
        """
        Insert a new job or update an existing job.

        Returns:
            True if a new job was inserted.
            False if an existing job was updated.
        """
        job_url = self._get_job_value(job, "job_url")

        if not job_url:
            job_url = self._get_job_value(job, "url")

        if not job_url:
            raise ValueError("Cannot save a job without a job URL.")

        now = datetime.now().isoformat(timespec="seconds")

        discovered_at = self._get_job_value(
            job,
            "discovered_at",
            now,
        )

        updated_at = self._get_job_value(
            job,
            "updated_at",
            now,
        )

        applied_at = self._get_job_value(
            job,
            "applied_at",
            None,
        )

        values = {
            "job_url": job_url,
            "source": self._get_job_value(job, "source", ""),
            "title": self._get_job_value(job, "title", ""),
            "company": self._get_job_value(job, "company", ""),
            "location": self._get_job_value(job, "location", ""),
            "posted_date": self._get_job_value(job, "posted_date", ""),
            "description": self._get_job_value(job, "description", ""),
            "match_score": self._get_job_value(job, "match_score"),
            "match_category": self._get_job_value(
                job,
                "match_category",
                "",
            ),
            "match_reasons": self._serialize_value(
                self._get_job_value(job, "match_reasons", [])
            ),
            "missing_keywords": self._serialize_value(
                self._get_job_value(job, "missing_keywords", [])
            ),
            "status": self._get_job_value(job, "status", "new"),
            "notes": self._get_job_value(job, "notes", ""),
            "discovered_at": discovered_at,
            "updated_at": updated_at,
            "applied_at": applied_at,
        }

        existing_job = self.connection.execute(
            """
            SELECT id
            FROM jobs
            WHERE job_url = ?
            """,
            (job_url,),
        ).fetchone()

        self.connection.execute(
            """
            INSERT INTO jobs (
                job_url,
                source,
                title,
                company,
                location,
                posted_date,
                description,
                match_score,
                match_category,
                match_reasons,
                missing_keywords,
                status,
                notes,
                discovered_at,
                updated_at,
                applied_at
            )
            VALUES (
                :job_url,
                :source,
                :title,
                :company,
                :location,
                :posted_date,
                :description,
                :match_score,
                :match_category,
                :match_reasons,
                :missing_keywords,
                :status,
                :notes,
                :discovered_at,
                :updated_at,
                :applied_at
            )
            ON CONFLICT(job_url) DO UPDATE SET
                source = excluded.source,
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                posted_date = excluded.posted_date,
                description = excluded.description,
                match_score = excluded.match_score,
                match_category = excluded.match_category,
                match_reasons = excluded.match_reasons,
                missing_keywords = excluded.missing_keywords,
                status = excluded.status,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            values,
        )

        self.connection.commit()

        return existing_job is None

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

        rows = self.connection.execute(
            query,
            parameters,
        ).fetchall()

        jobs: List[Dict[str, Any]] = []

        for row in rows:
            item = dict(row)

            item["match_reasons"] = self._deserialize_value(
                item.get("match_reasons")
            )

            item["missing_keywords"] = self._deserialize_value(
                item.get("missing_keywords")
            )

            jobs.append(item)

        return jobs

    def job_exists(self, job_url: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM jobs
            WHERE job_url = ?
            LIMIT 1
            """,
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

        if status == "applied":
            self.connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    notes = COALESCE(?, notes),
                    applied_at = ?,
                    updated_at = ?
                WHERE job_url = ?
                """,
                (
                    status,
                    notes,
                    now,
                    now,
                    job_url,
                ),
            )
        else:
            self.connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    notes = COALESCE(?, notes),
                    updated_at = ?
                WHERE job_url = ?
                """,
                (
                    status,
                    notes,
                    now,
                    job_url,
                ),
            )

        self.connection.commit()

    def update_job_match(
        self,
        job_url: str,
        match_score: float,
        match_category: str,
        match_reasons: Optional[List[str]] = None,
        missing_keywords: Optional[List[str]] = None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")

        self.connection.execute(
            """
            UPDATE jobs
            SET match_score = ?,
                match_category = ?,
                match_reasons = ?,
                missing_keywords = ?,
                updated_at = ?
            WHERE job_url = ?
            """,
            (
                match_score,
                match_category,
                self._serialize_value(match_reasons or []),
                self._serialize_value(missing_keywords or []),
                now,
                job_url,
            ),
        )

        self.connection.commit()

    def close(self) -> None:
        if self.connection:
            self.connection.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


if __name__ == "__main__":
    database_path = Path("data/jobs.db")

    with Database(database_path) as database:
        print("Database initialized successfully.")
        print(f"Database path: {database_path.resolve()}")
        print(f"Stored jobs: {len(database.get_jobs())}")
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.database import Database


def upsert_application_record(
    database: Database,
    job: dict[str, Any],
    review_url: str,
    status: str,
    unknown_questions: list[str] | None = None,
    filled_fields: list[str] | None = None,
) -> None:
    database.connection.execute(
        """
        INSERT INTO applications (
            job_url, title, company, review_url, status,
            unknown_questions, filled_fields, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_url) DO UPDATE SET
            title = excluded.title,
            company = excluded.company,
            review_url = excluded.review_url,
            status = excluded.status,
            unknown_questions = excluded.unknown_questions,
            filled_fields = excluded.filled_fields,
            updated_at = excluded.updated_at
        """,
        (
            job.get("job_url", ""),
            job.get("title", ""),
            job.get("company", ""),
            review_url,
            status,
            json.dumps(unknown_questions or [], ensure_ascii=False),
            json.dumps(filled_fields or [], ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    database.connection.commit()

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any


from src.config import load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SETTINGS = load_settings(PROJECT_ROOT / "config" / "settings.yaml")
DATABASE_PATH = PROJECT_ROOT / _SETTINGS.project.database_path
EXPORT_DIRECTORY = PROJECT_ROOT / _SETTINGS.project.export_directory
EXPORT_PATH = EXPORT_DIRECTORY / "matched_jobs.csv"


def convert_value(value: Any) -> Any:
    """
    Convert database values into CSV-friendly values.
    """
    if value is None:
        return ""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, (list, dict)):
        return json.dumps(
            value,
            ensure_ascii=False,
        )

    return value


def export_jobs_to_csv() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}"
        )

    EXPORT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        DATABASE_PATH
    )
    connection.row_factory = sqlite3.Row

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
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
                job_url,
                notes,
                discovered_at,
                updated_at,
                applied_at
            FROM jobs
            ORDER BY
                match_score DESC,
                discovered_at DESC
            """
        )

        rows = cursor.fetchall()

        if not rows:
            print("No jobs found in the database.")
            return

        column_names = rows[0].keys()

        with EXPORT_PATH.open(
            mode="w",
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=column_names,
            )

            writer.writeheader()

            for row in rows:
                writer.writerow(
                    {
                        column: convert_value(row[column])
                        for column in column_names
                    }
                )

        print("CSV export completed successfully.")
        print(f"Jobs exported: {len(rows)}")
        print(f"Export file: {EXPORT_PATH}")

    finally:
        connection.close()


if __name__ == "__main__":
    export_jobs_to_csv()
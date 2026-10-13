"""
Two-way bridge between this agent and the "Job Application" Claude project.

    python -m src.project_sync            # import Claude's updates, then export a fresh snapshot
    python -m src.project_sync --export   # only write the snapshot
    python -m src.project_sync --import   # only apply Claude's updates

The discovery pipeline runs this automatically at the end of every run.

Everything lives in ``project_sync/`` at the project root:

Agent -> Claude (rewritten every run, never edit by hand)
    jobs_for_review.csv     open jobs scoring >= REVIEW_MIN_SCORE, best first
    job_descriptions.jsonl  full job description per job_url (for tailoring)
    tracker.csv             every job you have acted on (applied, interviewing, ...)
    open_questions.md       real screening questions the form filler could not answer
    sync_summary.md         counts and freshness of this snapshot

Claude -> agent (written by Claude, consumed on the next run)
    inbox/status_updates.csv   job_url,status,notes
        Applied to SQLite, then moved to inbox/processed/.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from src.database import Database

logger = logging.getLogger(__name__)

SYNC_DIRNAME = "project_sync"
REVIEW_MIN_SCORE = 45

# Statuses Claude (or you) may set. "new"/"review" are open; the rest close a
# job so the agent stops re-tailoring and re-preparing it.
OPEN_STATUSES = {"new", "review", "shortlisted"}
CLOSED_STATUSES = {"applied", "interviewing", "offer", "rejected", "skipped"}
ALLOWED_STATUSES = OPEN_STATUSES | CLOSED_STATUSES

# Form fields that are page plumbing (login walls, tracking, search boxes),
# not screening questions. Seen in the applications table.
_JUNK_FIELD = re.compile(
    r"^(trk|loginCsrfParam|session_\w+|controlId|pageInstance|geoId|"
    r"upsellOrderOrigin|password|first-name|last-name|csrf\w*)$"
    r"|search (job titles|skills)|^(first|last) name\b|^location location",
    re.IGNORECASE,
)

REVIEW_COLUMNS = [
    "job_url", "match_score", "match_category", "company", "title", "location",
    "experience", "posted_on", "source", "job_status", "application_status",
    "has_tailored_docs", "match_reasons", "missing_keywords",
]
TRACKER_COLUMNS = [
    "job_url", "company", "title", "match_score", "job_status",
    "application_status", "applied_at", "updated_at", "notes",
]


def sync_directory(project_root: Path) -> Path:
    return project_root / SYNC_DIRNAME


def is_real_question(text: str) -> bool:
    text = (text or "").strip()
    return len(text) > 3 and not _JUNK_FIELD.search(text)


def _join(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    # utf-8-sig so Excel opens it with the right encoding.
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _join(row.get(column)) for column in columns})
            count += 1
    return count


# ----------------------------------------------------------------------
# Export: agent -> Claude
# ----------------------------------------------------------------------


def export_snapshot(database: Database, out_dir: Path, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "inbox").mkdir(exist_ok=True)

    jobs = database.get_jobs()
    applications = database.get_applications()
    documents = database.get_tailored_documents()

    merged: list[dict[str, Any]] = []
    for job in jobs:
        application = applications.get(job["job_url"], {})
        merged.append({
            **job,
            "job_status": job.get("status") or "new",
            "application_status": application.get("status", ""),
            "unknown_questions": application.get("unknown_questions"),
            "has_tailored_docs": "yes" if job["job_url"] in documents else "no",
        })

    review = sorted(
        (
            row for row in merged
            if row["job_status"] in OPEN_STATUSES
            and (row.get("match_score") or 0) >= REVIEW_MIN_SCORE
            and row.get("application_status") != "Rejected by quality filters"
        ),
        key=lambda row: -(row.get("match_score") or 0),
    )
    review_count = _write_csv(out_dir / "jobs_for_review.csv", REVIEW_COLUMNS, review)

    with (out_dir / "job_descriptions.jsonl").open("w", encoding="utf-8") as file:
        for row in review:
            file.write(json.dumps({
                "job_url": row["job_url"],
                "company": row.get("company"),
                "title": row.get("title"),
                "description": row.get("description") or "",
            }, ensure_ascii=False) + "\n")

    # Your pipeline, not the agent's own quality-filter rejections.
    tracked = [
        row for row in merged
        if (row["job_status"] not in ("new", "review")
            and not (row.get("notes") or "").startswith("Rejected by quality filters"))
        or row.get("application_status") == "Submitted"
    ]
    tracked.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
    tracker_count = _write_csv(out_dir / "tracker.csv", TRACKER_COLUMNS, tracked)

    questions: Counter[str] = Counter()
    for row in merged:
        if row["job_status"] in CLOSED_STATUSES:
            continue
        raw = row.get("unknown_questions") or "[]"
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            items = []
        for question in items or []:
            if is_real_question(question):
                questions[question.strip()] += 1
    lines = [
        "# Open screening questions",
        "",
        f"Snapshot: {now:%Y-%m-%d %H:%M}. Questions the form filler could not answer,",
        "most frequent first. Approved answers go in config/application_profile.yaml.",
        "",
    ]
    lines += [f"- ({count}x) {question}" for question, count in questions.most_common()] or ["_None._"]
    (out_dir / "open_questions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    status_counts = Counter(row["job_status"] for row in merged)
    band = Counter(row.get("match_category") or "-" for row in review)
    summary = [
        "# Job search agent snapshot",
        "",
        f"- Generated: {now:%Y-%m-%d %H:%M}",
        f"- Jobs in database: {len(merged)}",
        f"- Latest discovery: {max((row.get('discovered_at') or '' for row in merged), default='-')}",
        f"- Open jobs for review (score >= {REVIEW_MIN_SCORE}): {review_count} "
        + ", ".join(f"{name} {count}" for name, count in band.most_common()),
        f"- Tailored document sets: {len(documents)}",
        "- Job status: " + ", ".join(f"{name} {count}" for name, count in sorted(status_counts.items())),
        f"- Real open screening questions: {len(questions)}",
    ]
    (out_dir / "sync_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    logger.info("Project sync export: %s review, %s tracked, %s questions -> %s",
                review_count, tracker_count, len(questions), out_dir)
    return {"review": review_count, "tracked": tracker_count, "questions": len(questions)}


# ----------------------------------------------------------------------
# Import: Claude -> agent
# ----------------------------------------------------------------------


def import_updates(database: Database, out_dir: Path, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now()
    inbox = out_dir / "inbox" / "status_updates.csv"
    result = {"applied": 0, "skipped": 0}
    if not inbox.is_file():
        return result

    known = database.get_job_urls()
    with inbox.open("r", encoding="utf-8-sig", newline="") as file:
        for line_number, row in enumerate(csv.DictReader(file), start=2):
            url = (row.get("job_url") or "").strip()
            status = (row.get("status") or "").strip().lower()
            notes = (row.get("notes") or "").strip() or None
            if status not in ALLOWED_STATUSES:
                logger.warning("status_updates.csv line %s: unknown status %r", line_number, status)
                result["skipped"] += 1
                continue
            if url not in known:
                logger.warning("status_updates.csv line %s: job not in database: %s", line_number, url)
                result["skipped"] += 1
                continue
            database.update_job_status(url, status, notes)
            result["applied"] += 1

    processed = out_dir / "inbox" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    inbox.replace(processed / f"status_updates_{now:%Y%m%d_%H%M%S}.csv")
    logger.info("Project sync import: %s updates applied, %s skipped", result["applied"], result["skipped"])
    return result


def sync_project(database: Database, project_root: Path) -> None:
    """Import first so the snapshot already reflects Claude's decisions."""
    out_dir = sync_directory(project_root)
    import_updates(database, out_dir)
    export_snapshot(database, out_dir)


def main(argv: list[str] | None = None) -> None:
    from src.pipelines.discovery_pipeline import configure_logging, load_context

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", action="store_true", help="Only write the snapshot")
    parser.add_argument("--import", dest="do_import", action="store_true", help="Only apply Claude's updates")
    args = parser.parse_args(argv)

    context = load_context()
    configure_logging(context)
    out_dir = sync_directory(context.project_root)
    with Database(context.database_path) as database:
        if args.do_import or not args.export:
            import_updates(database, out_dir)
        if args.export or not args.do_import:
            export_snapshot(database, out_dir)
    print(f"Project sync folder: {out_dir}")


if __name__ == "__main__":
    main()

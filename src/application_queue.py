from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
from typing import Any, Iterable
from playwright.sync_api import sync_playwright

from src.application_assistant import EasyApplyAssistant


def create_application_review_page(
    jobs: Iterable[dict[str, Any]],
    export_directory: str | Path,
    run_date: date | None = None,
) -> Path:
    """Create a local review page and return its path."""
    output_directory = Path(export_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    current_date = run_date or date.today()
    jobs_list = list(jobs)
    page_path = output_directory / (
        f"application_review_{current_date.isoformat()}.html"
    )

    question_set: set[str] = set()
    sections: list[str] = []
    for index, job in enumerate(jobs_list, start=1):
        questions = job.get("unknown_questions", []) or []
        question_set.update(str(question) for question in questions)
        job_url = str(job.get("job_url") or "")
        status = str(job.get("application_status") or "Pending preparation")
        review_link = f"application_review_{current_date.isoformat()}.html#{index}"
        sections.append(
            f"<article id='{index}'>"
            f"<h2>{escape(str(job.get('title') or 'Untitled'))}</h2>"
            f"<p>{escape(str(job.get('company') or ''))} | "
            f"{escape(str(job.get('location') or ''))}</p>"
            f"<p>Status: <strong>{escape(status)}</strong></p>"
            f"<p><a href='{escape(job_url)}' target='_blank'>"
            "Open job/application page</a></p>"
            f"<p>Questions found: {len(questions)}</p>"
            "</article>"
        )

    question_fields = "".join(
        f"<label>{escape(question)}"
        f"<input name='question' value='{escape(question)}' readonly>"
        "<input name='answer' placeholder='Answer once for future applications'>"
        "</label>"
        for question in sorted(question_set)
    ) or "<p>No unanswered questions recorded yet.</p>"

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Application Review {escape(current_date.isoformat())}</title>
<style>
body {{ font-family: sans-serif; max-width: 960px; margin: 2rem auto; line-height: 1.5; }}
article {{ border: 1px solid #ccc; padding: 1rem; margin: 1rem 0; }}
a {{ color: #0645ad; }}
</style>
</head>
<body>
<h1>Application Review Queue</h1>
<p>Review each application before submitting. Submission is never automatic.</p>
<h2>Unique unanswered questions</h2>
<form method="post" action="http://127.0.0.1:8765/answers">
{question_fields}
<button type="submit">Save answers to application_profile.yaml</button>
</form>
<h2>Applications ({len(jobs_list)})</h2>
{''.join(sections)}
</body>
</html>
"""
    page_path.write_text(html, encoding="utf-8")
    return page_path


def excel_review_link(page_path: Path, job_index: int) -> str:
    """Return a relative link suitable for an Excel hyperlink cell."""
    return f"{page_path.name}#{job_index}"


def prepare_new_applications(
    jobs: Iterable[dict[str, Any]],
    profile_path: str | Path,
    max_jobs: int = 10,
) -> list[dict[str, Any]]:
    """Open new job URLs and fill known fields without submitting."""
    prepared_jobs: list[dict[str, Any]] = []
    job_list = list(jobs)
    if max_jobs > 0:
        job_list = job_list[:max_jobs]

    if not job_list:
        return prepared_jobs

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        try:
            for job in job_list:
                prepared = dict(job)
                url = str(job.get("job_url") or "")
                if not url:
                    prepared["application_status"] = "Missing job URL"
                    prepared_jobs.append(prepared)
                    continue

                try:
                    page.goto(url, wait_until="domcontentloaded")
                    review = EasyApplyAssistant(
                        page,
                        profile_path,
                    ).prepare()
                    prepared["unknown_questions"] = (
                        review.unknown_questions
                    )
                    prepared["application_status"] = (
                        "Ready for review"
                        if review.ready_for_review
                        else "Answers needed"
                    )
                    prepared["filled_fields"] = review.filled_fields
                except Exception as error:
                    prepared["application_status"] = (
                        f"Preparation failed: {error}"
                    )
                    prepared["unknown_questions"] = []

                prepared_jobs.append(prepared)
        finally:
            browser.close()

    return prepared_jobs

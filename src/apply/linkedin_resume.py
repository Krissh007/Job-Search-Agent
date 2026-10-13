"""
Re-upload your resume to LinkedIn (Jobs -> Application settings), so the
copy LinkedIn attaches to Easy Apply is always the latest file.

    python -m src.apply.linkedin_resume              # upload now
    python -m src.apply.linkedin_resume --dry-run    # only check the file and sign-in

Not scheduled: run it after updating your resume. Uses the agent's
signed-in browser profile (python -m src.apply.linkedin login).

After a confirmed upload, older copies of the same file name are deleted
(LinkedIn keeps at most a few resumes). Older copies are only deleted when
the new upload is confirmed, so you are never left without a resume.
The result of each run is written to project_sync/resume_upload_status.md.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Locator, Page

from src.apply.linkedin import (
    SecurityCheckError,
    check_for_security_page,
    is_signed_in,
    signed_in_browser,
)
from src.pipelines.discovery_pipeline import RunContext, configure_logging, load_context

logger = logging.getLogger(__name__)

SETTINGS_URL = "https://www.linkedin.com/jobs/application-settings/"
FILE_INPUT = "input[type='file']"
MAX_BYTES = 2 * 1024 * 1024  # LinkedIn's limit
ALLOWED_SUFFIXES = (".pdf", ".docx", ".doc")
# The persistent profile can only be open once; the 07:30 run may still be
# auto-applying, so wait and retry.
LAUNCH_RETRIES = 6
LAUNCH_RETRY_SECONDS = 300


class ResumeUploadError(RuntimeError):
    pass


def check_file(path: Path) -> None:
    if not path.is_file():
        raise ResumeUploadError(
            f"Resume not found: {path}. Put the file there or change "
            "resume_upload.file in config/settings.yaml."
        )
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ResumeUploadError(f"LinkedIn accepts {ALLOWED_SUFFIXES}, not {path.suffix}")
    if path.stat().st_size > MAX_BYTES:
        raise ResumeUploadError(f"{path.name} is over LinkedIn's 2 MB limit")


def _today_patterns(today: date) -> list[str]:
    # LinkedIn shows dates like 10/5/2026, 05/10/2026 or "Oct 5, 2026"
    # depending on locale.
    return [
        f"{today.month}/{today.day}/{today.year}",
        f"{today.day}/{today.month}/{today.year}",
        f"{today:%m/%d/%Y}",
        f"{today:%d/%m/%Y}",
        f"{today:%b} {today.day}, {today.year}",
        f"{today.day} {today:%b} {today.year}",
    ]


def resume_cards(page: Page, file_name: str) -> list[Locator]:
    """Visible resume entries whose text includes the file name (stem match,
    since LinkedIn may drop the extension)."""
    stem = Path(file_name).stem.lower()
    cards: list[Locator] = []
    for candidate in page.locator("li, [class*='resume'], [class*='document']").all():
        try:
            if not candidate.is_visible():
                continue
            text = candidate.inner_text().lower()
        except Exception:
            continue
        if stem in text and len(text) < 600:
            # Keep the innermost element per entry.
            if any(card.inner_text().lower() == text for card in cards):
                continue
            cards.append(candidate)
    return cards


def _is_from_today(card: Locator, today: date) -> bool:
    text = card.inner_text()
    return any(pattern in text for pattern in _today_patterns(today))


def _has_date(card: Locator) -> bool:
    return bool(re.search(r"\d{1,2}/\d{1,2}/\d{4}|[A-Z][a-z]{2} \d{1,2}, \d{4}|\d{1,2} [A-Z][a-z]{2} \d{4}", card.inner_text()))


def delete_card(page: Page, card: Locator) -> bool:
    menu = card.locator("button[aria-label*='more' i], button[aria-label*='options' i]").first
    if not menu.count():
        return False
    menu.click()
    page.wait_for_timeout(800)
    delete = (
        page.locator("[role='menu'], .artdeco-dropdown__content")
        .get_by_text(re.compile(r"^\s*delete\s*$", re.I))
        .first
    )
    if not delete.count():
        page.keyboard.press("Escape")
        return False
    delete.click()
    page.wait_for_timeout(800)
    confirm = page.get_by_role("dialog").get_by_role("button", name=re.compile(r"^\s*delete\s*$", re.I)).first
    if confirm.count():
        confirm.click()
        page.wait_for_timeout(1_500)
    return True


def upload(page: Page, path: Path, today: date | None = None, keep_only_latest: bool = True) -> str:
    """Upload the file on the application-settings page; return a status line."""
    today = today or date.today()
    file_input = page.locator(FILE_INPUT).first
    if not file_input.count():
        raise ResumeUploadError("No upload control on LinkedIn's application settings page (layout changed?)")
    before = len(resume_cards(page, path.name))

    file_input.set_input_files(str(path))
    confirmed = False
    for _ in range(30):
        page.wait_for_timeout(1_000)
        cards = resume_cards(page, path.name)
        if len(cards) > before or any(_is_from_today(card, today) for card in cards):
            confirmed = True
            break
    if not confirmed:
        raise ResumeUploadError("Upload not confirmed by LinkedIn within 30 s; older copies left untouched")

    deleted = 0
    if keep_only_latest:
        for _ in range(5):
            stale = [
                card for card in resume_cards(page, path.name)
                if _has_date(card) and not _is_from_today(card, today)
            ]
            if not stale or not delete_card(page, stale[0]):
                break
            deleted += 1
    return f"Uploaded {path.name}; removed {deleted} older cop{'y' if deleted == 1 else 'ies'}"


def write_status(context: RunContext, ok: bool, message: str) -> None:
    # JARVIS reads this file for "did my resume upload work?".
    out = context.project_root / "project_sync"
    out.mkdir(parents=True, exist_ok=True)
    (out / "resume_upload_status.md").write_text(
        f"# LinkedIn resume re-upload\n\n- Last run: {datetime.now():%Y-%m-%d %H:%M}\n"
        f"- Result: {'OK' if ok else 'FAILED'}\n- Detail: {message}\n",
        encoding="utf-8",
    )


def run(context: RunContext, dry_run: bool = False) -> bool:
    settings = context.settings.resume_upload
    path = context.path(settings.file)
    try:
        check_file(path)
    except ResumeUploadError as error:
        logger.error("%s", error)
        write_status(context, False, str(error))
        return False

    last_error: Exception | None = None
    for attempt in range(1, LAUNCH_RETRIES + 1):
        try:
            with signed_in_browser(context) as browser:
                if not is_signed_in(browser):
                    raise ResumeUploadError("Not signed in. Run: python -m src.apply.linkedin login")
                if dry_run:
                    print(f"OK: {path.name} is valid and LinkedIn is signed in.")
                    return True
                page = browser.new_page()
                page.goto(SETTINGS_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(4_000)
                check_for_security_page(page)
                message = upload(page, path, keep_only_latest=settings.keep_only_latest)
            logger.info("LinkedIn resume: %s", message)
            write_status(context, True, message)
            return True
        except (ResumeUploadError, SecurityCheckError) as error:
            logger.error("LinkedIn resume upload failed: %s", error)
            write_status(context, False, str(error))
            return False
        except Exception as error:  # usually: profile still in use by the 07:30 run
            last_error = error
            logger.warning("Browser not available (attempt %s/%s): %s", attempt, LAUNCH_RETRIES, error)
            if attempt < LAUNCH_RETRIES:
                time.sleep(LAUNCH_RETRY_SECONDS)
    write_status(context, False, f"Browser profile unavailable: {last_error}")
    return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Only check the file and the LinkedIn sign-in")
    args = parser.parse_args(argv)
    context = load_context()
    configure_logging(context)
    if not context.settings.resume_upload.enabled and not args.dry_run:
        print("resume_upload.enabled is false in config/settings.yaml")
        return
    raise SystemExit(0 if run(context, args.dry_run) else 1)


if __name__ == "__main__":
    main()

"""
The agent's own signed-in LinkedIn browser profile.

One-time sign-in (you type your password; the agent never sees it):
    python -m src.apply.linkedin login

JobPilot's LinkedIn apply agent and src.apply.linkedin_resume reuse this
profile and the helpers below. Applying itself lives in JobPilot.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

from src.pipelines.discovery_pipeline import RunContext, configure_logging, load_context

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.linkedin.com/login"
SESSION_COOKIE = "li_at"
# Any of these in the URL means LinkedIn wants a human: stop immediately.
SECURITY_CHECK_MARKERS = ("checkpoint", "challenge", "captcha", "authwall", "/login", "/uas/")

class SecurityCheckError(RuntimeError):
    """LinkedIn showed a sign-in, checkpoint or CAPTCHA page."""


# ----------------------------------------------------------------------
# Browser profile
# ----------------------------------------------------------------------


@contextmanager
def signed_in_browser(context: RunContext) -> Iterator[BrowserContext]:
    settings = context.settings.easy_apply
    profile_dir = context.path(settings.browser_profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        options: dict[str, Any] = {
            "headless": False,
            "viewport": None,
            "locale": "en-IN",
            "timezone_id": context.settings.project.timezone,
        }
        try:
            browser = playwright.chromium.launch_persistent_context(
                str(profile_dir), channel=settings.browser_channel, **options
            )
        except Exception as error:
            logger.warning("Could not start %s (%s); using Playwright Chromium.", settings.browser_channel, error)
            browser = playwright.chromium.launch_persistent_context(str(profile_dir), **options)
        try:
            yield browser
        finally:
            try:
                browser.close()
            except Exception:
                pass


def is_signed_in(browser: BrowserContext) -> bool:
    return any(
        cookie["name"] == SESSION_COOKIE and cookie["value"]
        for cookie in browser.cookies("https://www.linkedin.com")
    )


def check_for_security_page(page: Page) -> None:
    url = page.url.lower()
    if any(marker in url for marker in SECURITY_CHECK_MARKERS):
        raise SecurityCheckError(
            f"LinkedIn showed a sign-in or security check ({page.url}). "
            "Stopping. Run 'python -m src.apply.linkedin login' and complete it yourself."
        )


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


def login(context: RunContext, timeout_minutes: int = 10) -> bool:
    with signed_in_browser(context) as browser:
        if is_signed_in(browser):
            print("Already signed in to LinkedIn in the agent's browser profile.")
            return True

        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(LOGIN_URL)
        print("Sign in to LinkedIn in the browser window (type your password there).")
        print(f"Waiting up to {timeout_minutes} minutes...")

        deadline = time.monotonic() + timeout_minutes * 60
        while time.monotonic() < deadline:
            try:
                signed_in = is_signed_in(browser)
                on_checkpoint = "checkpoint" in page.url
            except Exception:
                print("The browser window was closed before sign-in finished. Run the command again.")
                return False
            if signed_in and not on_checkpoint:
                print("Signed in. The session is saved in the agent's browser profile.")
                print("You can close the browser window.")
                time.sleep(2)
                return True
            time.sleep(2)

    print("Timed out before sign-in finished. Run the command again.")
    return False


CLOSED_JOB_STATUSES = ("rejected", "skipped", "applied", "interviewing", "offer")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sign in to LinkedIn in the agent's browser profile.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="Sign in once in the agent's browser profile.")
    parser.parse_args(argv)

    context = load_context()
    configure_logging(context)
    sys.exit(0 if login(context) else 1)


if __name__ == "__main__":
    main()

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.application_assistant import EasyApplyAssistant


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_ROOT / "config" / "application_profile.yaml"


def test_prepare_fills_known_fields_and_blocks_unknown_questions() -> None:
    html = """
    <form>
      <input name="email" placeholder="Email">
      <input name="current_location" placeholder="Current location">
      <input name="years_experience" placeholder="Years of experience">
      <button type="submit">Submit</button>
    </form>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        assistant = EasyApplyAssistant(page, PROFILE_PATH)

        review = assistant.prepare()

        assert page.locator("input[name='email']").input_value() == ""
        assert page.locator(
            "input[name='current_location']"
        ).input_value() == "Hyderabad, India"
        assert len(review.unknown_questions) == 1
        assert "Years of experience" in review.unknown_questions[0]
        assert not review.ready_for_review

        with pytest.raises(ValueError):
            assistant.submit(review, confirm=True)

        browser.close()


def test_submit_requires_explicit_confirmation() -> None:
    html = """
    <form onsubmit="event.preventDefault(); document.title='submitted';">
      <input name="known_answer" placeholder="work authorization">
      <button type="submit">Submit</button>
    </form>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        assistant = EasyApplyAssistant(page, PROFILE_PATH)
        review = assistant.prepare()

        with pytest.raises(PermissionError):
            assistant.submit(review)

        browser.close()

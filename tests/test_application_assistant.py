from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.application_assistant import EasyApplyAssistant


# A sample profile, so the tests never depend on the candidate's own
# (git-ignored) config/application_profile.yaml.
SAMPLE_PROFILE = """
contact:
  full_name: Test Candidate
  email: ""
  current_location: Hyderabad, India
screening_answers:
  work authorization: "Yes"
"""


@pytest.fixture
def profile_path(tmp_path: Path) -> Path:
    path = tmp_path / "application_profile.yaml"
    path.write_text(SAMPLE_PROFILE, encoding="utf-8")
    return path


def test_prepare_fills_known_fields_and_blocks_unknown_questions(profile_path: Path) -> None:
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
        assistant = EasyApplyAssistant(page, profile_path)

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


def test_submit_requires_explicit_confirmation(profile_path: Path) -> None:
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
        assistant = EasyApplyAssistant(page, profile_path)
        review = assistant.prepare()

        with pytest.raises(PermissionError):
            assistant.submit(review)

        browser.close()

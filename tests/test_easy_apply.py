"""
Offline tests for the Easy Apply filler against a mock of LinkedIn's
multi-step dialog. The most important property: Submit is never clicked.
"""

import pytest
from playwright.sync_api import sync_playwright

from src.apply.easy_apply import (
    ALREADY_APPLIED,
    ANSWERS_NEEDED,
    NOT_EASY_APPLY,
    READY_TO_SUBMIT,
    EasyApplyFiller,
    answer_for,
    build_answers,
)

ANSWERS = build_answers(
    {
        "contact": {"full_name": "Test Candidate", "phone": "9999999999", "current_location": "Hyderabad"},
        "application": {"notice_period_days": "30"},
        "screening_answers": {
            "years of experience": "4",
            "years of work experience do you have with sql": "3",
            "comfortable working from office": "Yes",
        },
    }
)

# Step 1: contact (email pre-filled by LinkedIn), step 2: screening
# questions, step 3: review with the Submit button.
JOB_PAGE = """
<main>
  <h1>Business Analyst</h1>
  <button id="easy" aria-label="Easy Apply to Business Analyst at Acme">Easy Apply</button>
</main>
<div role="dialog" id="promo">Try Premium</div>
<div role="dialog" id="dialog" style="display:none">
  <div class="step" data-step="1">
    <label for="first">First name</label><input id="first" required>
    <label for="email">Email address</label><input id="email" value="prefilled@example.com">
    <label for="phone">Mobile phone number</label><input id="phone" required>
    <button class="next" aria-label="Continue to next step">Next</button>
  </div>
  <div class="step" data-step="2" style="display:none">
    <label for="sql">How many years of work experience do you have with SQL?</label><input id="sql" required>
    <label for="total">Total years of experience?</label><input id="total" required>
    <label for="notice">Notice period (days)</label>
      <select id="notice"><option>Select an option</option><option>15</option><option>30</option></select>
    <fieldset><legend>Are you comfortable working from office?</legend>
      <label for="yes">Yes</label><input type="radio" id="yes" name="office">
      <label for="no">No</label><input type="radio" id="no" name="office">
    </fieldset>
    EXTRA_QUESTION
    <button class="next" aria-label="Review your application">Review</button>
  </div>
  <div class="step" data-step="3" style="display:none">
    <button id="submit" aria-label="Submit application">Submit application</button>
  </div>
</div>
<script>
  window.submitted = false;
  document.getElementById('easy').onclick = () => {
    document.getElementById('dialog').style.display = 'block';
    // LinkedIn adds an empty overlay dialog after the form (Sep 2026).
    document.body.insertAdjacentHTML('beforeend', '<div role="dialog" id="overlay"></div>');
  };
  document.querySelectorAll('.next').forEach(button => button.onclick = () => {
    const step = button.closest('.step');
    const missing = [...step.querySelectorAll('[required]')].filter(input => !input.value);
    step.querySelectorAll('.error').forEach(error => error.remove());
    if (missing.length) {
      missing.forEach(input => input.insertAdjacentHTML('afterend', '<span role="alert" class="error">Please enter a valid answer</span>'));
      return;
    }
    step.style.display = 'none';
    step.nextElementSibling.style.display = 'block';
  });
  document.getElementById('submit').onclick = () => { window.submitted = true; };
</script>
"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


def run(browser, html):
    page = browser.new_page()
    page.set_content(html)
    result = EasyApplyFiller(page, ANSWERS, max_steps=6).prepare()
    return page, result


def test_fills_every_step_and_stops_before_submit(browser):
    page, result = run(browser, JOB_PAGE.replace("EXTRA_QUESTION", ""))

    assert result.status == READY_TO_SUBMIT
    assert result.unknown_questions == []
    assert page.evaluate("window.submitted") is False
    assert page.locator("#submit").is_visible()

    assert page.locator("#first").input_value() == "Test"
    assert page.locator("#phone").input_value() == "9999999999"
    assert page.locator("#email").input_value() == "prefilled@example.com"
    # The more specific answer wins for the SQL question.
    assert page.locator("#sql").input_value() == "3"
    assert page.locator("#total").input_value() == "4"
    assert page.locator("#notice").input_value() == "30"
    assert page.locator("#yes").is_checked()


def test_unknown_required_question_stops_for_the_candidate(browser):
    extra = '<label for="visa">Do you require visa sponsorship?</label><input id="visa" required>'
    page, result = run(browser, JOB_PAGE.replace("EXTRA_QUESTION", extra))

    assert result.status == ANSWERS_NEEDED
    assert "Do you require visa sponsorship?" in result.unknown_questions
    assert page.evaluate("window.submitted") is False
    assert page.locator("#visa").is_visible()


def test_external_apply_is_not_easy_apply(browser):
    _, result = run(browser, "<main><h1>BA</h1><a href='https://example.com'>Apply</a></main>")
    assert result.status == NOT_EASY_APPLY


def test_already_applied_is_detected(browser):
    _, result = run(browser, "<main><h1>BA</h1><span>Applied 3 days ago</span></main>")
    assert result.status == ALREADY_APPLIED


def test_confirmation_is_detected(browser):
    page = browser.new_page()
    page.set_content("<div role='dialog'>Your application was sent to Acme!</div>")
    assert EasyApplyFiller.application_sent(page)


def test_longest_matching_answer_wins():
    answers = {"years of experience": "4", "years of experience with sql": "3"}
    assert answer_for("Years of experience with SQL?", answers) == "3"
    assert answer_for("Years of experience in banking?", answers) == "4"
    assert answer_for("Visa sponsorship?", answers) == ""

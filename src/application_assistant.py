from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import Page


@dataclass
class ApplicationQuestion:
    label: str
    selector: str
    answer: str = ""
    known: bool = False


@dataclass
class ApplicationReview:
    url: str
    questions: list[ApplicationQuestion] = field(default_factory=list)
    unknown_questions: list[str] = field(default_factory=list)
    filled_fields: list[str] = field(default_factory=list)

    @property
    def ready_for_review(self) -> bool:
        return not self.unknown_questions


class EasyApplyAssistant:
    """Prepare supported application forms without submitting them implicitly."""

    FIELD_SELECTORS = {
        "full_name": "input[name*='name' i], input[id*='name' i]",
        "email": "input[type='email'], input[name*='email' i]",
        "phone": "input[type='tel'], input[name*='phone' i]",
        "current_location": "input[name*='location' i], input[id*='location' i]",
        "notice_period_days": "input[name*='notice' i], input[id*='notice' i]",
        "expected_ctc_lpa": "input[name*='salary' i], input[name*='ctc' i]",
    }

    def __init__(
        self,
        page: Page,
        profile_path: str | Path,
    ) -> None:
        self.page = page
        self.profile = self._load_profile(profile_path)

    @staticmethod
    def _load_profile(profile_path: str | Path) -> dict[str, Any]:
        path = Path(profile_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, dict):
            raise ValueError("Application profile must be a YAML object")
        return data

    def prepare(self) -> ApplicationReview:
        """Fill known profile fields and answer only known questions."""
        review = ApplicationReview(url=self.page.url)
        contact = self.profile.get("contact", {})
        application = self.profile.get("application", {})

        values = {**contact, **application}
        for field_name, selector in self.FIELD_SELECTORS.items():
            value = str(values.get(field_name) or "").strip()
            if not value:
                continue
            locator = self.page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.fill(value)
            review.filled_fields.append(field_name)

        resume_path = str(contact.get("resume_path") or "").strip()
        if resume_path:
            file_input = self.page.locator(
                "input[type='file']"
            ).first
            if file_input.count() > 0:
                file_input.set_input_files(resume_path)
                review.filled_fields.append("resume_path")

        self._review_screening_questions(review)
        return review

    def _review_screening_questions(
        self,
        review: ApplicationReview,
    ) -> None:
        answers = self.profile.get("screening_answers", {})
        controls = self.page.locator(
            "input, textarea, select"
        )

        for index in range(controls.count()):
            control = controls.nth(index)
            label = self._control_label(control)
            if not label:
                continue

            if self._is_profile_field(label):
                continue

            answer = self._answer_for(label, answers)
            selector = f"input, textarea, select >> nth={index}"
            question = ApplicationQuestion(
                label=label,
                selector=selector,
                answer=answer,
                known=bool(answer),
            )
            review.questions.append(question)

            if answer:
                self._fill_control(control, answer)
            else:
                review.unknown_questions.append(label)

    @staticmethod
    def _is_profile_field(label: str) -> bool:
        normalized = label.lower()
        return any(
            term in normalized
            for term in (
                "full_name",
                "email",
                "phone",
                "current_location",
                "notice_period_days",
                "expected_ctc_lpa",
            )
        )

    @staticmethod
    def _control_label(control: Any) -> str:
        aria_label = control.get_attribute("aria-label") or ""
        placeholder = control.get_attribute("placeholder") or ""
        name = control.get_attribute("name") or ""
        return " ".join(
            part.strip() for part in [aria_label, placeholder, name]
            if part.strip()
        )

    @staticmethod
    def _answer_for(label: str, answers: dict[str, Any]) -> str:
        normalized = label.lower()
        for question, answer in answers.items():
            if str(question).lower() in normalized:
                return str(answer or "").strip()
        return ""

    @staticmethod
    def _fill_control(control: Any, answer: str) -> None:
        tag_name = control.evaluate("element => element.tagName.toLowerCase()")
        if tag_name == "select":
            try:
                control.select_option(label=answer)
            except Exception:
                control.select_option(value=answer)
        else:
            control.fill(answer)

    def submit(self, review: ApplicationReview, confirm: bool = False) -> None:
        """Submit only after explicit confirmation and no unknown questions."""
        if not confirm:
            raise PermissionError(
                "Submission requires explicit confirm=True after review."
            )
        if not review.ready_for_review:
            raise ValueError(
                "Unknown screening questions must be answered manually."
            )

        submit_button = self.page.locator(
            "button[type='submit'], input[type='submit']"
        ).last
        if submit_button.count() == 0:
            raise LookupError("No application submit button found.")
        submit_button.click()

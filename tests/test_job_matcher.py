from pathlib import Path

import pytest

from src.config import load_matching_rules
from src.matching.job_matcher import JobMatcher, contains_phrase
from src.models import Job
from src.resume_profile import load_resume_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def matcher():
    profile = load_resume_profile(PROJECT_ROOT / "config" / "candidate_profile.yaml")
    rules = load_matching_rules(PROJECT_ROOT / "config" / "matching_rules.yaml")
    return JobMatcher(profile, rules)


@pytest.fixture
def sample_job():
    return Job(
        job_url="https://example.com/jobs/1",
        source="test",
        title="AI Business Analyst",
        company="Example Analytics",
        location="Hyderabad",
        description=(
            "We need a Business Analyst with requirements gathering, "
            "stakeholder management, SQL, UAT, and product analytics "
            "experience."
        ),
    )


def test_match_result_shape(matcher, sample_job):
    result = matcher.match(sample_job)
    assert 0 <= result["match_score"] <= 100
    assert result["match_category"] in {"Strong", "Good", "Review", "Low"}
    assert result["match_reasons"]
    assert isinstance(result["missing_keywords"], list)
    assert isinstance(result["eligible"], bool)


def test_unrelated_job_scores_low(matcher):
    job = Job(
        title="Nursing Assistant",
        company="City Hospital",
        location="Hyderabad",
        description="Provide patient care in ICU ward.",
    )
    assert matcher.match(job)["match_score"] < 50


def test_score_job_alias(matcher, sample_job):
    assert matcher.score_job(sample_job) == matcher.match(sample_job)


# ----------------------------------------------------------------------
# ISS-15: whole-word matching
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, term",
    [
        ("we maintain systems in chennai", "ai"),
        ("keep average coverage and leverage storage", "rag"),
        ("evaluate graduate candidates", "uat"),
        ("contact our salesforce team", "sql"),
    ],
)
def test_short_terms_do_not_match_inside_words(text, term):
    assert not contains_phrase(text, term)


@pytest.mark.parametrize(
    "text, term",
    [
        ("build ai-powered analytics", "ai"),
        ("rag pipelines on llm outputs", "rag"),
        ("coordinate uat, sit and regression", "uat"),
        ("(sql) and python", "sql"),
    ],
)
def test_short_terms_match_as_whole_words(text, term):
    assert contains_phrase(text, term)


def test_substrings_do_not_count_as_evidence(matcher):
    # Every profile term here appears only inside another word.
    job = Job(
        title="Operations Executive",
        location="Chennai",
        description=(
            "Maintain average coverage, leverage storage and evaluate "
            "graduate trainees."
        ),
    )
    result = matcher.match(job)
    assert "AI" not in result["match_reasons"]
    assert "RAG" not in result["match_reasons"]
    assert "UAT" not in result["match_reasons"]


# ----------------------------------------------------------------------
# ISS-2: Associate Product Manager is a target role
# ----------------------------------------------------------------------


def test_associate_product_manager_is_a_role_match(matcher):
    job = Job(
        title="Associate Product Manager",
        location="Hyderabad",
        source="naukri",
        experience="3-5 Yrs",
        experience_min=3,
        experience_max=5,
        description=(
            "Write user stories and acceptance criteria, work on product "
            "analytics and stakeholder management for our SaaS platform."
        ),
    )
    result = matcher.match(job)
    assert any("Associate Product Manager" in reason for reason in result["match_reasons"])
    assert result["eligible"], result["rejection_reasons"]


# ----------------------------------------------------------------------
# ISS-6: experience range from structured fields
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "low, high, eligible",
    [(3, 5, True), (2, 4, True), (5, 10, True), (0, 2, False), (6, 10, False), (7, 12, False)],
)
def test_experience_range_overlap(matcher, sample_job, low, high, eligible):
    sample_job.experience_min = low
    sample_job.experience_max = high
    result = matcher.match(sample_job)
    experience_rejected = any("experience" in reason.lower() for reason in result["rejection_reasons"])
    assert experience_rejected is not eligible


def test_structured_experience_beats_text(matcher, sample_job):
    # The company history in the text must not override the 3-5 range.
    sample_job.description += " Our firm has 25 years of history."
    sample_job.experience_min, sample_job.experience_max = 3, 5
    assert not any("experience" in r.lower() for r in matcher.match(sample_job)["rejection_reasons"])


# ----------------------------------------------------------------------
# ISS-9: India eligibility for remote roles
# ----------------------------------------------------------------------


def _remote_job(source: str, description: str) -> Job:
    return Job(
        title="Business Analyst",
        location="Remote",
        source=source,
        description="Requirements gathering, UAT and SQL. " + description,
    )


def test_remote_foreign_role_is_rejected(matcher):
    job = _remote_job("indeed", "Must overlap with EST hours for our Chicago office.")
    assert "Location is not India-eligible" in matcher.match(job)["rejection_reasons"]


def test_remote_role_mentioning_india_is_eligible(matcher):
    job = _remote_job("indeed", "Remote within India.")
    assert "Location is not India-eligible" not in matcher.match(job)["rejection_reasons"]


def test_remote_role_on_india_portal_is_eligible(matcher):
    job = _remote_job("naukri", "")
    assert "Location is not India-eligible" not in matcher.match(job)["rejection_reasons"]


def test_foreign_location_is_rejected(matcher):
    job = Job(title="Business Analyst", location="London, UK", description="UAT and SQL")
    assert "Location is not India-eligible" in matcher.match(job)["rejection_reasons"]


# ----------------------------------------------------------------------
# ISS-7: bands and preferred locations come from config
# ----------------------------------------------------------------------


def test_category_bands_are_configurable():
    matcher = JobMatcher({}, {"categories": {"strong": 90, "good": 80, "review": 70}})
    assert matcher.category_for(85) == "Good"
    assert matcher.category_for(75) == "Review"
    assert matcher.category_for(65) == "Low"


def test_preferred_locations_are_configurable():
    profile = {"target_roles": ["Business Analyst"]}
    pune = Job(title="Business Analyst", location="Pune")
    assert not JobMatcher(profile, {"preferred_locations": ["Hyderabad"]}).match(pune)["match_reasons"][1:]
    reasons = JobMatcher(profile, {"preferred_locations": ["Pune"]}).match(pune)["match_reasons"]
    assert "Preferred location: Pune" in reasons

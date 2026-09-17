from pathlib import Path

from src.config_manager import ConfigManager
from src.matching.job_matcher import JobMatcher
from src.models import Job
from src.resume_profile import load_resume_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_matcher() -> JobMatcher:
    profile = load_resume_profile(
        PROJECT_ROOT / "config" / "candidate_profile.yaml"
    )
    rules = ConfigManager(
        PROJECT_ROOT / "config" / "matching_rules.yaml"
    ).all()
    return JobMatcher(profile, rules)


def test_resume_profile_loads_configured_tools() -> None:
    profile = load_resume_profile(
        PROJECT_ROOT / "config" / "candidate_profile.yaml"
    )

    assert "SQL" in profile.tools_technologies


def test_resume_match_handles_reordered_phrases() -> None:
    matcher = create_matcher()

    result = matcher.match(
        Job(
            title="Business Analyst",
            location="Pune",
            description="Gather business requirements and coordinate UAT.",
        )
    )

    assert "Business requirements gathering" in result["match_reasons"]
    assert "UAT" in result["match_reasons"]
    assert result["match_score"] >= 35


def test_irrelevant_role_scores_low() -> None:
    matcher = create_matcher()

    result = matcher.match(
        Job(
            title="Senior Java Backend Developer",
            location="Bengaluru",
            description="Build Spring Boot services and Kafka pipelines.",
        )
    )

    assert result["match_score"] < 45
    assert result["match_category"] == "Low"


def test_domain_and_experience_alignment_affect_score() -> None:
    matcher = create_matcher()

    aligned = matcher.match(
        Job(
            title="AI Business Analyst",
            location="Hyderabad",
            description=(
                "Business requirements and product analytics for an "
                "enterprise SaaS AI analytics platform."
            ),
        )
    )
    generic = matcher.match(
        Job(
            title="AI Business Analyst",
            location="Hyderabad",
            description="Business requirements for an internal project.",
        )
    )

    assert aligned["match_score"] > generic["match_score"]
    assert "Enterprise SaaS" in aligned["match_reasons"]
    assert "Product Analytics" in aligned["match_reasons"]


def test_foreign_location_is_not_eligible() -> None:
    matcher = create_matcher()

    result = matcher.match(
        Job(
            title="Business Analyst",
            location="Atlanta, GA, United States",
            description=(
                "Gather business requirements and coordinate UAT "
                "for an enterprise SaaS platform."
            ),
        )
    )

    assert result["eligible"] is False
    assert "Location is not India-eligible" in result["rejection_reasons"]


def test_title_only_match_is_not_eligible() -> None:
    matcher = create_matcher()

    result = matcher.match(
        Job(
            title="Business Analyst",
            location="Hyderabad",
            description="General office administration.",
        )
    )

    assert result["eligible"] is False
    assert any(
        "Insufficient resume evidence" in reason
        for reason in result["rejection_reasons"]
    )


def test_experience_mismatch_is_rejected() -> None:
    matcher = JobMatcher(
        {
            "target_roles": ["Business Analyst"],
            "experience_years_min": 2,
            "experience_years_max": 4,
        },
        {
            "india_only": True,
            "scoring": {"minimum_evidence_matches": 1},
        },
    )

    result = matcher.match(
        Job(
            title="Business Analyst",
            location="Hyderabad",
            description="Requires 8 years of experience and SQL.",
        )
    )

    assert result["eligible"] is False
    assert "Required experience exceeds the candidate range" in result[
        "rejection_reasons"
    ]

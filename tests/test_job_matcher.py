from src.config_manager import ConfigManager
from src.matching.job_matcher import JobMatcher
from src.models import Job
from src.resume_profile import load_resume_profile


def main() -> None:
    profile = load_resume_profile()
    config = ConfigManager()
    matcher = JobMatcher(profile, config.matching_rules)

    job = Job(
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

    result = matcher.match(job)

    print("Match completed.")
    print(f"Score: {result.score}")
    print(f"Category: {result.category}")
    print(f"Reasons: {result.reasons}")
    print(f"Missing keywords: {result.missing_keywords}")


if __name__ == "__main__":
    main()
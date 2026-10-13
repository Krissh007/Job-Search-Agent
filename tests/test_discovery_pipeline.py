"""
The search engine (discover -> score) with a fake discoverer, so no browser
or network is needed. JobPilot calls these same functions through its shim.
"""

from datetime import date
from pathlib import Path

import pytest

from src.config import load_matching_rules, load_settings
from src.models import Job
from src.pipelines.discovery_pipeline import RunContext, RunStats, run, score_jobs
from src.resume_profile import load_resume_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 24)

GOOD_DESCRIPTION = (
    "Gather business requirements, write BRDs and user stories, coordinate "
    "UAT, work with stakeholders, and use SQL for product analytics in an "
    "AI-powered enterprise SaaS platform."
)


def make_jobs() -> list[Job]:
    return [
        Job(
            title="AI Business Analyst",
            company="Fresh Fit",
            location="Hyderabad",
            job_url="https://example.com/jobs/fresh-fit",
            source="naukri",
            experience="3-5 Yrs",
            posted_date="2 days ago",
            description=GOOD_DESCRIPTION,
        ),
        Job(
            title="Business Analyst",
            company="Stale Co",
            location="Hyderabad",
            job_url="https://example.com/jobs/stale",
            source="naukri",
            experience="3-5 Yrs",
            posted_date="3 weeks ago",
            description=GOOD_DESCRIPTION,
        ),
        Job(
            title="Lead Business Analyst",
            company="Senior Co",
            location="Hyderabad",
            job_url="https://example.com/jobs/too-senior",
            source="naukri",
            experience="8-13 Yrs",
            posted_date="1 day ago",
            description=GOOD_DESCRIPTION,
        ),
        Job(
            title="Java Developer",
            company="Other Co",
            location="Hyderabad",
            job_url="https://example.com/jobs/unrelated",
            source="naukri",
            posted_date="1 day ago",
            description="Spring Boot microservices and Kafka.",
        ),
    ]


@pytest.fixture
def context(tmp_path) -> RunContext:
    settings = load_settings(PROJECT_ROOT / "config" / "settings.yaml")
    settings.project.database_path = str(tmp_path / "jobs.db")
    settings.project.log_directory = str(tmp_path / "logs")
    return RunContext(
        project_root=PROJECT_ROOT,
        settings=settings,
        rules=load_matching_rules(PROJECT_ROOT / "config" / "matching_rules.yaml"),
        profile=load_resume_profile(PROJECT_ROOT / "config" / "candidate_profile.yaml"),
    )


def fake_discover(jobs):
    def discover(context, known_urls, stats):
        found = [job for job in jobs if job.job_url not in known_urls]
        stats.discovered = len(found)
        return found

    return discover


def test_score_jobs_drops_stale_and_ineligible_jobs(context):
    stats = RunStats()
    matched = score_jobs(make_jobs(), context, stats, today=TODAY)

    assert stats.stale == 1
    assert stats.rejected == 2
    assert [job.company for job in matched] == ["Fresh Fit"]
    job = matched[0]
    assert job.experience_min == 3 and job.posted_on == "2026-09-22"
    assert job.eligible and job.match_score >= 45 and job.match_reasons


def test_dry_run_skips_known_urls_and_saves_nothing(context, tmp_path):
    stats, matched = run(
        context,
        discover=fake_discover(make_jobs()),
        known_urls={"https://example.com/jobs/fresh-fit"},
        today=TODAY,
    )

    assert stats.discovered == 3
    assert matched == []
    assert not (tmp_path / "jobs.db").exists()

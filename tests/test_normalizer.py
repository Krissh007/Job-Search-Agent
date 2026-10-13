from datetime import date

import pytest

from src.models import Job
from src.normalizer import JobNormalizer, parse_experience_range


@pytest.mark.parametrize(
    "text, expected",
    [
        ("3-5 Yrs", (3, 5)),
        ("3 - 5 years", (3, 5)),
        ("5 to 10 Yrs", (5, 10)),
        ("5+ years", (5, None)),
        ("2 yrs", (2, 2)),
        ("Full-time", (None, None)),
        ("", (None, None)),
    ],
)
def test_parse_experience_range(text, expected):
    assert parse_experience_range(text) == expected


def test_normalizes_aliases_and_whitespace():
    job = JobNormalizer().normalize(
        {
            "job_title": "  AI   Business Analyst ",
            "company_name": " Example  Analytics ",
            "city": " Hyderabad ",
            "url": "https://example.com/jobs/1",
            "portal": "Naukri",
        },
        observed_on=date(2026, 9, 24),
    )
    assert isinstance(job, Job)
    assert job.title == "AI Business Analyst"
    assert job.company == "Example Analytics"
    assert job.location == "Hyderabad"
    assert job.job_url == "https://example.com/jobs/1"
    assert job.source == "naukri"


def test_posted_on_is_absolute():
    job = JobNormalizer().normalize(
        {"title": "BA", "posted_date": "3 days ago"},
        observed_on=date(2026, 9, 24),
    )
    assert job.posted_on == "2026-09-21"


def test_experience_in_job_type_is_moved():
    # Jobs saved by older Naukri code carry experience in job_type.
    job = JobNormalizer().normalize({"title": "BA", "job_type": "4-7 Yrs"})
    assert job.experience == "4-7 Yrs"
    assert job.job_type == ""
    assert (job.experience_min, job.experience_max) == (4, 7)

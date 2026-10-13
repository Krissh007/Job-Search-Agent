from datetime import date

from src.freshness import is_within_freshness, posted_age_days


def test_posted_age_parses_relative_values() -> None:
    assert posted_age_days({"posted_date": "3 days ago"}) == 3
    assert posted_age_days({"posted_date": "2 weeks ago"}) == 14
    assert posted_age_days({"posted_date": "today"}) == 0
    assert posted_age_days({"posted_date": "unknown"}) is None


def test_freshness_window_needs_a_known_age() -> None:
    assert is_within_freshness({"posted_days": "3"}, 7)
    assert not is_within_freshness({"posted_days": "31"}, 30)
    assert not is_within_freshness({"posted_days": ""}, 30)


def test_age_keeps_counting_from_posted_on() -> None:
    job = {"posted_on": "2026-09-14", "posted_date": "3 days ago"}
    assert posted_age_days(job, today=date(2026, 9, 24)) == 10
    assert not is_within_freshness(job, 7, today=date(2026, 9, 24))


def test_posted_age_handles_naukri_variants() -> None:
    assert posted_age_days({"posted_date": "3+ weeks ago"}) == 21
    assert posted_age_days({"posted_date": "30+ days ago"}) == 30
    assert posted_age_days({"posted_date": "Just now"}) == 0
    assert posted_age_days({"posted_date": "Few hours ago"}) == 0
    assert posted_age_days({"posted_date": "1 month ago"}) == 30

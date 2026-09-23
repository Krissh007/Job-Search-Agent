from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")


def _get(job: Any, key: str) -> Any:
    if isinstance(job, dict):
        return job.get(key)
    return getattr(job, key, None)


def _parse_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        pass
    for format_string in DATE_FORMATS:
        try:
            return datetime.strptime(value, format_string).date()
        except ValueError:
            continue
    return None


def relative_age_days(posted_text: str) -> int | None:
    """Age in days described by portal text such as '3 days ago'."""
    value = str(posted_text or "").strip().lower()
    if not value:
        return None

    if any(term in value for term in ("today", "just posted", "just now", "few hours")):
        return 0

    # Portals write "3+ weeks ago" / "30+ days ago" for older postings; the
    # number is then a lower bound, which is enough for freshness checks.
    if re.search(r"\d+\+?\s*(?:hours?|minutes?|mins?)\s+ago", value):
        return 0

    for unit, days in (("days?", 1), ("weeks?", 7), ("months?", 30)):
        match = re.search(rf"(\d+)\+?\s*{unit}\s+ago", value)
        if match:
            return int(match.group(1)) * days

    return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).rstrip("+"))
    except ValueError:
        return None


def derive_posted_on(job: Any, observed_on: date) -> str:
    """
    Convert what the portal said on ``observed_on`` into an absolute ISO
    date. Returns '' when the source did not expose a posting age.
    """
    posted_date = str(_get(job, "posted_date") or "")

    absolute = _parse_date(posted_date)
    if absolute is not None:
        return absolute.isoformat()

    age = _int_or_none(_get(job, "posted_days"))
    if age is None:
        age = relative_age_days(posted_date)
    if age is None:
        return ""

    return (observed_on - timedelta(days=age)).isoformat()


def posted_age_days(job: Any, today: date | None = None) -> int | None:
    """Return the job's posting age in days, or None when unknown."""
    current_date = today or date.today()

    posted_on = _parse_date(str(_get(job, "posted_on") or ""))
    if posted_on is not None:
        return max(0, (current_date - posted_on).days)

    age = _int_or_none(_get(job, "posted_days"))
    if age is not None:
        return age

    posted_date = str(_get(job, "posted_date") or "")
    absolute = _parse_date(posted_date)
    if absolute is not None:
        return max(0, (current_date - absolute).days)

    return relative_age_days(posted_date)


def is_within_freshness(
    job: Any,
    max_days: int,
    today: date | None = None,
) -> bool:
    """Return true only when a job has verifiable age within the window."""
    age_days = posted_age_days(job, today)
    return age_days is not None and age_days <= max_days

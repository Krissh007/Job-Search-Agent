from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def posted_age_days(job: dict[str, Any], today: date | None = None) -> int | None:
    """Return the job's posting age in days when the source provides it."""
    posted_days = job.get("posted_days")

    if posted_days not in (None, ""):
        try:
            return int(str(posted_days).rstrip("+"))
        except ValueError:
            pass

    value = str(job.get("posted_date") or "").strip().lower()

    if not value:
        return None

    if "today" in value or "just posted" in value:
        return 0

    match = re.search(r"(\d+)\s+(?:hours?|minutes?)\s+ago", value)
    if match:
        return 0

    match = re.search(r"(\d+)\s+days?\s+ago", value)
    if match:
        return int(match.group(1))

    match = re.search(r"(\d+)\s+weeks?\s+ago", value)
    if match:
        return int(match.group(1)) * 7

    for format_string in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            posted_date = datetime.strptime(
                value,
                format_string,
            ).date()
            current_date = today or date.today()
            return max(0, (current_date - posted_date).days)
        except ValueError:
            continue

    return None


def is_within_freshness(
    job: dict[str, Any],
    max_days: int,
) -> bool:
    """Return true only when a job has verifiable age within the window."""
    age_days = posted_age_days(job)
    return age_days is not None and age_days <= max_days

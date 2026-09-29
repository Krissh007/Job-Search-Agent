from __future__ import annotations

from typing import Any

# Names accepted in settings.yaml ``sources``. Kept free of imports so config
# validation does not load Playwright.
SOURCE_NAMES = frozenset({"naukri", "indeed", "linkedin"})


def create_source(
    name: str,
    page: Any,
    enrich_details: bool = False,
    debug_directory: str = "data/debug",
    posted_within_days: int | None = None,
) -> Any:
    """Build the adapter for one configured source."""
    name = name.lower().strip()

    if name == "naukri":
        from src.sources.naukri_source import NaukriSource

        return NaukriSource(
            page=page,
            enrich_details=enrich_details,
            debug_directory=debug_directory,
        )

    if name == "indeed":
        from src.sources.indeed_source import IndeedSource

        return IndeedSource(page=page, debug_directory=debug_directory)

    if name == "linkedin":
        from src.sources.linkedin_source import LinkedInSource

        return LinkedInSource(
            page=page,
            enrich_details=enrich_details,
            posted_within_days=posted_within_days,
            debug_directory=debug_directory,
        )

    raise ValueError(f"Unsupported source: {name}")

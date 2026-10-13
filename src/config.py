from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(ValueError):
    """Raised when a configuration file is missing or invalid."""


class _StrictModel(BaseModel):
    # Unknown keys are rejected so a misspelled or obsolete setting fails
    # loudly instead of being silently ignored.
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------------
# settings.yaml
# ----------------------------------------------------------------------


class ProjectSettings(_StrictModel):
    name: str = "job_search_agent"
    timezone: str = "Asia/Kolkata"
    database_path: str = "data/jobs.db"
    export_directory: str = "data/exports"
    log_directory: str = "data/logs"
    debug_directory: str = "data/debug"


class BrowserSettings(_StrictModel):
    headless: bool = False
    default_timeout_ms: int = Field(30_000, gt=0)
    navigation_timeout_ms: int = Field(60_000, gt=0)


class SearchSettings(_StrictModel):
    keywords: list[str] = Field(default_factory=lambda: ["Business Analyst"])
    locations: list[str] = Field(default_factory=lambda: ["Hyderabad"])
    max_results_per_query: int = Field(60, gt=0)
    max_pages_per_source: int = Field(10, gt=0)
    max_posted_days: int = Field(7, ge=0)
    freshness_windows_days: list[int] = Field(default_factory=lambda: [7])
    enrich_details: bool = False

    @model_validator(mode="after")
    def _check_lists(self) -> "SearchSettings":
        if not self.keywords:
            raise ValueError("search.keywords must list at least one keyword")
        if not self.locations:
            raise ValueError("search.locations must list at least one location")
        if not self.freshness_windows_days:
            raise ValueError("search.freshness_windows_days must not be empty")
        return self


class ApplicationSettings(_StrictModel):
    prepare_after_search: bool = False
    max_jobs_per_run: int = Field(10, ge=0)


class TailoringSettings(_StrictModel):
    """Tailored resume + cover letter generation for high-scoring jobs."""

    enabled: bool = False
    # Only jobs scoring at least this much get documents.
    min_match_score: int = Field(60, ge=0, le=100)
    # Your original resume (.docx, .pdf, .txt or .md). The only source of facts.
    master_resume_path: str = "config/master_resume.docx"
    output_directory: str = "data/applications"
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    # Tried in order when the main model fails or its free quota runs out.
    fallback_models: list[str] = Field(default_factory=lambda: ["gemini-3.5-flash-lite"])
    api_key_env: str = "GEMINI_API_KEY"
    temperature: float = Field(0.3, ge=0, le=1)
    # 0 = no limit. Keeps a run inside the free tier's daily quota.
    max_jobs_per_run: int = Field(15, ge=0)
    # Pause between model calls to stay under per-minute free-tier limits.
    seconds_between_requests: float = Field(6, ge=0)
    # Jobs whose saved description is shorter than this are skipped: there
    # is not enough text to tailor against.
    min_description_chars: int = Field(300, ge=0)


class EasyApplySettings(_StrictModel):
    """LinkedIn Easy Apply in the agent's own signed-in browser profile."""

    # Holds the LinkedIn session cookies: git-ignored, never share it.
    browser_profile_dir: str = "data/browser_profile"
    # "chrome" uses your installed Google Chrome; falls back to Playwright's
    # Chromium when Chrome is not installed.
    browser_channel: str = "chrome"
    min_match_score: int = Field(60, ge=0, le=100)
    # Small batches keep the account's activity close to a person's.
    max_jobs_per_run: int = Field(5, ge=1, le=25)
    seconds_between_jobs: float = Field(20, ge=5)
    max_steps_per_application: int = Field(8, ge=1)


class AutoApplySettings(_StrictModel):
    """
    Unattended applying (python -m src.apply.auto_apply, run by src.daily).
    Submits only forms that are completely answered from
    application_profile.yaml; anything with an unknown question is left
    unsubmitted and its questions go to project_sync/open_questions.md.
    """

    enabled: bool = False
    # Portals to apply on, in order.
    sources: list[str] = Field(default_factory=lambda: ["linkedin", "naukri"])
    # Only jobs Claude/you marked "shortlisted" in the project sync.
    shortlisted_only: bool = True
    min_match_score: int = Field(60, ge=0, le=100)
    # Submissions per calendar day across all portals.
    daily_cap: int = Field(10, ge=0, le=50)

    @model_validator(mode="after")
    def _check_sources(self) -> "AutoApplySettings":
        unknown = [name for name in self.sources if name not in ("linkedin", "naukri")]
        if unknown:
            raise ValueError(f"auto_apply.sources: unsupported {unknown}; use linkedin, naukri")
        return self


class ResumeUploadSettings(_StrictModel):
    """Weekday re-upload of your resume to LinkedIn (src.apply.linkedin_resume)."""

    enabled: bool = False
    # .pdf, .docx or .doc, at most 2 MB.
    file: str = "config/linkedin_resume.docx"
    # Delete older copies of the same file name after a confirmed upload.
    keep_only_latest: bool = True


class Settings(_StrictModel):
    project: ProjectSettings = Field(default_factory=ProjectSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    sources: list[str] = Field(default_factory=lambda: ["naukri"])
    application: ApplicationSettings = Field(default_factory=ApplicationSettings)
    easy_apply: EasyApplySettings = Field(default_factory=EasyApplySettings)
    auto_apply: AutoApplySettings = Field(default_factory=AutoApplySettings)
    resume_upload: ResumeUploadSettings = Field(default_factory=ResumeUploadSettings)
    tailoring: TailoringSettings = Field(default_factory=TailoringSettings)

    @model_validator(mode="after")
    def _check_sources(self) -> "Settings":
        # Imported lazily so config validation has no browser dependency.
        from src.sources import SOURCE_NAMES

        unknown = [name for name in self.sources if name.lower() not in SOURCE_NAMES]
        if unknown:
            raise ValueError(
                f"Unknown sources {unknown}; supported: {sorted(SOURCE_NAMES)}"
            )
        self.sources = [name.lower() for name in self.sources]
        return self


# ----------------------------------------------------------------------
# matching_rules.yaml
# ----------------------------------------------------------------------


class ScoringWeights(_StrictModel):
    role_match: int = 40
    proven_skill: int = 3
    proven_skill_max: int = 30
    responsibility: int = 2
    responsibility_max: int = 20
    preferred_location: int = 10
    tool: int = 1
    tool_max: int = 10
    domain_match: int = 2
    domain_match_max: int = 10
    experience_area: int = 2
    experience_area_max: int = 10

    @property
    def maximum_score(self) -> int:
        return (
            self.role_match
            + self.proven_skill_max
            + self.responsibility_max
            + self.preferred_location
            + self.tool_max
            + self.domain_match_max
            + self.experience_area_max
        )


class CategoryBands(_StrictModel):
    strong: int = 75
    good: int = 60
    review: int = 45

    @model_validator(mode="after")
    def _check_order(self) -> "CategoryBands":
        if not self.strong >= self.good >= self.review:
            raise ValueError("categories must satisfy strong >= good >= review")
        return self


class MatchingRules(_StrictModel):
    scoring: ScoringWeights = Field(default_factory=ScoringWeights)
    minimum_match_score: int = Field(45, ge=0, le=100)
    minimum_evidence_matches: int = Field(2, ge=0)
    india_only: bool = True
    # Portals that list India jobs by default; a job from one of these
    # with a bare "Remote" location is treated as India-eligible.
    india_portals: list[str] = Field(default_factory=lambda: ["naukri"])
    excluded_domains: list[str] = Field(default_factory=list)
    categories: CategoryBands = Field(default_factory=CategoryBands)
    preferred_locations: list[str] = Field(
        default_factory=lambda: ["Hyderabad", "Remote"]
    )
    skill_aliases: dict[str, list[str]] = Field(default_factory=dict)


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------


def read_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML file that must contain a mapping."""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        with config_path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except yaml.YAMLError as error:
        raise ConfigError(f"Invalid YAML in {config_path}: {error}") from error

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping")
    return data


def validate_model(model: type[BaseModel], data: dict[str, Any], source: str) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or '(root)'}: {item['msg']}"
            for item in error.errors()
        )
        raise ConfigError(f"Invalid configuration in {source}: {problems}") from error


def load_settings(path: str | Path) -> Settings:
    return validate_model(Settings, read_yaml(path), str(path))


def load_matching_rules(path: str | Path) -> MatchingRules:
    return validate_model(MatchingRules, read_yaml(path), str(path))


def parse_matching_rules(data: dict[str, Any] | MatchingRules | None) -> MatchingRules:
    """Accept an already-built model, a plain dict, or None (defaults)."""
    if isinstance(data, MatchingRules):
        return data
    return validate_model(MatchingRules, data or {}, "matching rules")

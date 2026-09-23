from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from src.config import ConfigError, validate_model, read_yaml


class ResumeProfile(BaseModel):
    """Structured evidence from the candidate's resume, used for scoring."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    target_roles: list[str] = Field(default_factory=list)
    proven_skills: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    tools_technologies: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "tools_technologies",
            "tools_and_technologies",
            "tools",
        ),
    )
    experience_summary: str = ""
    experience_areas: list[str] = Field(default_factory=list)
    experience_years_min: float | None = None
    experience_years_max: float | None = None

    @field_validator("experience_years_min", "experience_years_max", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        return None if value in ("", None) else value

    @model_validator(mode="after")
    def _check_range(self) -> "ResumeProfile":
        if (
            self.experience_years_min is not None
            and self.experience_years_max is not None
            and self.experience_years_min > self.experience_years_max
        ):
            raise ValueError("experience_years_min must be <= experience_years_max")
        return self


def parse_resume_profile(data: dict[str, Any] | ResumeProfile | None) -> ResumeProfile:
    """Accept an already-built profile, a plain dict, or None."""
    if isinstance(data, ResumeProfile):
        return data
    return validate_model(ResumeProfile, data or {}, "candidate profile")


def load_resume_profile(file_path: str | Path) -> ResumeProfile:
    """Load and validate the candidate profile YAML file."""
    profile_path = Path(file_path)
    if profile_path.exists() and not profile_path.is_file():
        raise ConfigError(f"Candidate profile path is not a file: {profile_path}")
    return validate_model(ResumeProfile, read_yaml(profile_path), str(profile_path))

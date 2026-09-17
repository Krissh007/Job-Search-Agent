from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml


@dataclass
class ResumeProfile:
    """
    Structured representation of the candidate profile.
    """

    target_roles: List[str] = field(default_factory=list)
    proven_skills: List[str] = field(default_factory=list)
    industries: List[str] = field(default_factory=list)
    responsibilities: List[str] = field(default_factory=list)
    tools_technologies: List[str] = field(default_factory=list)
    experience_summary: str = ""
    experience_areas: List[str] = field(default_factory=list)
    experience_years_min: str | float = ""
    experience_years_max: str | float = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResumeProfile":
        """
        Create a ResumeProfile object from YAML data.
        """

        return cls(
            target_roles=data.get("target_roles", []),
            proven_skills=data.get("proven_skills", []),
            industries=data.get("industries", []),
            responsibilities=data.get("responsibilities", []),
            tools_technologies=data.get(
                "tools_technologies",
                data.get(
                    "tools_and_technologies",
                    data.get("tools", []),
                ),
            ),
            experience_summary=data.get(
                "experience_summary",
                "",
            ),
            experience_areas=data.get(
                "experience_areas",
                [],
            ),
            experience_years_min=data.get(
                "experience_years_min",
                "",
            ),
            experience_years_max=data.get(
                "experience_years_max",
                "",
            ),
        )


def load_resume_profile(
    file_path: str | Path,
) -> ResumeProfile:
    """
    Load the candidate profile YAML file.
    """

    profile_path = Path(file_path)

    if not profile_path.is_absolute():
        profile_path = Path.cwd() / profile_path

    profile_path = profile_path.resolve()

    if not profile_path.exists():
        raise FileNotFoundError(
            f"Candidate profile file not found: {profile_path}"
        )

    if not profile_path.is_file():
        raise ValueError(
            f"Candidate profile path is not a file: {profile_path}"
        )

    with profile_path.open(
        mode="r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise ValueError(
            f"Candidate profile must contain a YAML dictionary: {profile_path}"
        )

    return ResumeProfile.from_dict(data)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print(
            "Usage: python -m src.resume_profile "
            "<path-to-candidate-profile.yaml>"
        )
        raise SystemExit(1)

    profile = load_resume_profile(sys.argv[1])

    print("Candidate profile loaded successfully.")
    print(profile)
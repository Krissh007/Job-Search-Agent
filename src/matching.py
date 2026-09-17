from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml


class JobMatcher:
    """
    Matches discovered jobs against:
    - config/candidate_profile.yaml
    - config/matching_rules.yaml
    """

    def __init__(
        self,
        candidate_profile_path: str | Path,
        matching_rules_path: str | Path,
    ) -> None:
        self.candidate_profile_path = Path(candidate_profile_path)
        self.matching_rules_path = Path(matching_rules_path)

        self.profile = self._load_yaml(self.candidate_profile_path)
        self.rules = self._load_yaml(self.matching_rules_path)

        self.target_roles = self._normalize_list(
            self.profile.get("target_roles", [])
        )
        self.proven_skills = self._normalize_list(
            self.profile.get("proven_skills", [])
        )
        self.responsibilities = self._normalize_list(
            self.profile.get("responsibilities", [])
        )
        self.tools = self._normalize_list(
            self.profile.get("tools_and_technologies", [])
        )
        self.industries = self._normalize_list(
            self.profile.get("industries", [])
        )

        self.preferred_locations = self._normalize_list(
            self.rules.get("preferred_locations", [])
        )

        self.skill_aliases = {
            self._normalize_text(key): self._normalize_list(values)
            for key, values in self.rules.get("skill_aliases", {}).items()
        }

        self.scoring = self.rules.get("scoring", {})
        self.categories = self.rules.get("categories", {})

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

        if not isinstance(data, dict):
            raise ValueError(f"Expected YAML object in: {path}")

        return data

    @staticmethod
    def _normalize_text(value: Any) -> str:
        text = str(value or "").lower()
        text = re.sub(r"[^a-z0-9+#./ -]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @classmethod
    def _normalize_list(cls, values: Any) -> list[str]:
        if not values:
            return []

        if isinstance(values, str):
            values = [values]

        return [
            cls._normalize_text(value)
            for value in values
            if cls._normalize_text(value)
        ]

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        if not term:
            return False

        if len(term) <= 3:
            return re.search(rf"\b{re.escape(term)}\b", text) is not None

        return term in text

    def _contains_any(self, text: str, terms: list[str]) -> bool:
        return any(self._contains_term(text, term) for term in terms)

    def _job_text(self, job: Any) -> str:
        if hasattr(job, "__dict__"):
            data = vars(job)
        elif isinstance(job, dict):
            data = job
        else:
            data = {}

        parts = [
            data.get("title", ""),
            data.get("company", ""),
            data.get("location", ""),
            data.get("description", ""),
            data.get("salary", ""),
            data.get("job_type", ""),
        ]

        return self._normalize_text(" ".join(str(part or "") for part in parts))

    def _job_value(self, job: Any, field: str) -> str:
        if hasattr(job, field):
            return str(getattr(job, field) or "")

        if isinstance(job, dict):
            return str(job.get(field, "") or "")

        return ""

    def _role_match(self, job_text: str) -> tuple[bool, str]:
        title = self._normalize_text(self._job_value_from_text(job_text))

        # Use the actual title separately when possible.
        return (
            self._contains_any(job_text, self.target_roles),
            "Target role or related role detected"
            if self._contains_any(job_text, self.target_roles)
            else "No direct target-role keyword detected",
        )

    @staticmethod
    def _job_value_from_text(job_text: str) -> str:
        return job_text

    def _find_matches(
        self,
        job_text: str,
        values: list[str],
        aliases: bool = False,
    ) -> list[str]:
        matched = []

        for value in values:
            search_terms = [value]

            if aliases and value in self.skill_aliases:
                search_terms.extend(self.skill_aliases[value])

            if self._contains_any(job_text, search_terms):
                matched.append(value)

        return matched

    def _location_match(self, job: Any) -> bool:
        location = self._normalize_text(self._job_value(job, "location"))

        if not location:
            return False

        return self._contains_any(location, self.preferred_locations)

    def _calculate_category(self, score: int) -> str:
        strong = int(self.categories.get("strong", 75))
        good = int(self.categories.get("good", 60))
        review = int(self.categories.get("review", 45))

        if score >= strong:
            return "Strong"
        if score >= good:
            return "Good"
        if score >= review:
            return "Review"
        return "Low"

    def match_job(self, job: Any) -> dict[str, Any]:
        job_text = self._job_text(job)

        title = self._normalize_text(self._job_value(job, "title"))
        location = self._normalize_text(self._job_value(job, "location"))

        matched_roles = [
            role
            for role in self.target_roles
            if self._contains_term(title, role)
        ]

        matched_skills = self._find_matches(
            job_text,
            self.proven_skills,
            aliases=True,
        )

        matched_responsibilities = self._find_matches(
            job_text,
            self.responsibilities,
        )

        matched_tools = self._find_matches(
            job_text,
            self.tools,
        )

        matched_industries = self._find_matches(
            job_text,
            self.industries,
        )

        missing_skills = [
            skill
            for skill in self.proven_skills
            if skill not in matched_skills
        ]

        role_points = int(self.scoring.get("role_match", 40))
        skill_points = int(self.scoring.get("proven_skill", 3))
        skill_max = int(self.scoring.get("proven_skill_max", 30))
        responsibility_points = int(self.scoring.get("responsibility", 2))
        responsibility_max = int(self.scoring.get("responsibility_max", 20))
        location_points = int(self.scoring.get("preferred_location", 10))
        tool_points = int(self.scoring.get("tool", 1))
        tool_max = int(self.scoring.get("tool_max", 10))

        role_score = role_points if matched_roles else 0
        skills_score = min(len(matched_skills) * skill_points, skill_max)
        responsibilities_score = min(
            len(matched_responsibilities) * responsibility_points,
            responsibility_max,
        )
        location_score = location_points if self._location_match(job) else 0
        tools_score = min(len(matched_tools) * tool_points, tool_max)

        raw_score = (
            role_score
            + skills_score
            + responsibilities_score
            + location_score
            + tools_score
        )

        maximum_score = (
            role_points
            + skill_max
            + responsibility_max
            + location_points
            + tool_max
        )

        normalized_score = round((raw_score / maximum_score) * 100)
        normalized_score = max(0, min(100, normalized_score))

        category = self._calculate_category(normalized_score)

        reason_parts = []

        if matched_roles:
            reason_parts.append(
                f"Role alignment: {', '.join(matched_roles[:3])}"
            )

        if matched_skills:
            reason_parts.append(
                f"Matching skills: {', '.join(matched_skills[:5])}"
            )

        if matched_responsibilities:
            reason_parts.append(
                f"Relevant responsibilities: "
                f"{', '.join(matched_responsibilities[:4])}"
            )

        if matched_tools:
            reason_parts.append(
                f"Tools: {', '.join(matched_tools[:4])}"
            )

        if matched_industries:
            reason_parts.append(
                f"Industry relevance: {', '.join(matched_industries[:3])}"
            )

        if self._location_match(job):
            reason_parts.append(f"Preferred location: {location}")

        if not reason_parts:
            reason_parts.append(
                "Limited matching information was available in the job listing."
            )

        result = {
            "match_score": normalized_score,
            "match_level": category,
            "matching_roles": matched_roles,
            "matching_skills": matched_skills,
            "missing_skills": missing_skills,
            "matched_responsibilities": matched_responsibilities,
            "matched_tools": matched_tools,
            "matched_industries": matched_industries,
            "preferred_location_match": self._location_match(job),
            "match_reason": ". ".join(reason_parts),
        }

        return result

    def enrich_job(self, job: Any) -> dict[str, Any]:
        """
        Returns the original job as a dictionary with matching fields added.
        """
        if hasattr(job, "__dict__"):
            result = asdict(job) if hasattr(job, "__dataclass_fields__") else vars(job).copy()
        elif isinstance(job, dict):
            result = dict(job)
        else:
            result = {}

        result.update(self.match_job(job))
        return result
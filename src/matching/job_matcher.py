from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List


class JobMatcher:
    """
    Matches normalized job records against the candidate profile.
    Supports both dictionaries and Python objects.
    """

    def __init__(
        self,
        resume_profile: Any = None,
        matching_rules: Dict[str, Any] | None = None,
    ) -> None:
        self.resume_profile = resume_profile
        self.matching_rules = matching_rules or {}

        self.scoring_rules = self.matching_rules.get(
            "scoring",
            {},
        )

    def match(self, job: Any) -> Dict[str, Any]:
        """
        Match a job against the candidate profile.

        The input may be:
        - a dictionary
        - a dataclass
        - an ordinary Python object
        """

        job_data = self._to_dict(job)

        title = self._text(job_data.get("title"))
        company = self._text(job_data.get("company"))
        location = self._text(job_data.get("location"))
        description = self._text(job_data.get("description"))
        source = self._text(job_data.get("source"))

        searchable_text = " ".join(
            [
                title,
                company,
                location,
                description,
            ]
        ).lower()

        score = 0
        reasons: List[str] = []
        missing_keywords: List[str] = []

        target_roles = self._profile_list("target_roles")
        proven_skills = self._profile_list("proven_skills")
        responsibilities = self._profile_list("responsibilities")
        # Candidate profiles created by earlier versions used
        # ``tools_and_technologies``.  Accept both spellings so the tools
        # evidence configured in the profile is actually considered.
        tools = self._profile_list("tools_technologies")
        if not tools:
            tools = self._profile_list("tools_and_technologies")
        industries = self._profile_list("industries")
        experience_areas = self._profile_list("experience_areas")
        preferred_locations = self._get_preferred_locations()
        minimum_evidence_matches = self._score_rule(
            "minimum_evidence_matches",
            2,
        )
        minimum_match_score = self._score_rule(
            "minimum_match_score",
            45,
        )

        role_weight = self._score_rule("role_match", 40)
        proven_skill_weight = self._score_rule("proven_skill", 3)
        proven_skill_max = self._score_rule("proven_skill_max", 30)
        responsibility_weight = self._score_rule("responsibility", 2)
        responsibility_max = self._score_rule("responsibility_max", 20)
        preferred_location_weight = self._score_rule(
            "preferred_location",
            10,
        )
        tool_weight = self._score_rule("tool", 1)
        tool_max = self._score_rule("tool_max", 10)
        domain_weight = self._score_rule("domain_match", 2)
        domain_max = self._score_rule("domain_match_max", 10)
        experience_weight = self._score_rule("experience_area", 2)
        experience_max = self._score_rule(
            "experience_area_max",
            10,
        )

        matched_roles = [
            role
            for role in target_roles
            if self._contains_phrase(searchable_text, role)
        ]

        if matched_roles:
            score += role_weight
            reasons.append(
                "Target role match: " + ", ".join(matched_roles)
            )
        else:
            missing_keywords.extend(target_roles[:3])

        skill_aliases = self.matching_rules.get(
            "skill_aliases",
            {},
        )

        matched_skills = [
            skill
            for skill in proven_skills
            if self._matches_profile_term(
                searchable_text,
                skill,
                skill_aliases,
            )
        ]

        skill_score = min(
            len(matched_skills) * proven_skill_weight,
            proven_skill_max,
        )
        score += skill_score

        reasons.extend(matched_skills)

        matched_responsibilities = [
            responsibility
            for responsibility in responsibilities
            if self._matches_profile_term(
                searchable_text,
                responsibility,
            )
        ]

        responsibility_score = min(
            len(matched_responsibilities) * responsibility_weight,
            responsibility_max,
        )
        score += responsibility_score

        reasons.extend(matched_responsibilities)

        matched_tools = [
            tool
            for tool in tools
            if self._matches_profile_term(
                searchable_text,
                tool,
            )
        ]

        tool_score = min(
            len(matched_tools) * tool_weight,
            tool_max,
        )
        score += tool_score

        reasons.extend(matched_tools)
        rejection_reasons: List[str] = []

        matched_industries = [
            industry
            for industry in industries
            if self._matches_profile_term(
                searchable_text,
                industry,
            )
        ]
        domain_score = min(
            len(matched_industries) * domain_weight,
            domain_max,
        )
        score += domain_score
        reasons.extend(matched_industries)

        if self._has_excluded_domain(
            searchable_text,
            matched_industries,
        ):
            rejection_reasons.append(
                "Job domain is outside the candidate profile"
            )

        matched_experience_areas = [
            area
            for area in experience_areas
            if self._matches_profile_term(
                searchable_text,
                area,
            )
        ]
        experience_score = min(
            len(matched_experience_areas) * experience_weight,
            experience_max,
        )
        score += experience_score
        reasons.extend(matched_experience_areas)

        matched_locations = [
            preferred_location
            for preferred_location in preferred_locations
            if self._contains_phrase(location.lower(), preferred_location)
            or self._contains_phrase(
                searchable_text,
                preferred_location,
            )
        ]

        if matched_locations:
            score += preferred_location_weight
            reasons.append(
                "Preferred location: "
                + ", ".join(matched_locations)
            )

        evidence_count = (
            len(matched_skills)
            + len(matched_responsibilities)
            + len(matched_tools)
            + len(matched_industries)
            + len(matched_experience_areas)
        )
        if self._india_only() and not self._is_india_eligible(
            location,
            searchable_text,
        ):
            rejection_reasons.append("Location is not India-eligible")

        if evidence_count < minimum_evidence_matches:
            rejection_reasons.append(
                "Insufficient resume evidence beyond the job title"
            )

        experience_rejection = self._experience_rejection(
            job_data,
            searchable_text,
        )
        if experience_rejection:
            rejection_reasons.append(experience_rejection)

        maximum_score = (
            role_weight
            + proven_skill_max
            + responsibility_max
            + preferred_location_weight
            + tool_max
            + domain_max
            + experience_max
        )
        normalized_score = round(
            (score / maximum_score) * 100
        ) if maximum_score else 0
        normalized_score = max(0, min(100, normalized_score))

        if normalized_score < minimum_match_score:
            rejection_reasons.append(
                "Match score is below the minimum threshold"
            )

        category = self._get_category(normalized_score)

        return {
            "title": title,
            "company": company,
            "location": location,
            "job_url": self._text(
                job_data.get("job_url")
                or job_data.get("url")
            ),
            "source": source,
            "description": description,
            "match_score": normalized_score,
            "match_category": category,
            "match_reasons": reasons,
            "missing_keywords": missing_keywords,
            "eligible": not rejection_reasons,
            "rejection_reasons": rejection_reasons,
            "evidence_count": evidence_count,
        }

    def score_job(self, job: Any) -> Dict[str, Any]:
        """
        Backward-compatible alias for match().
        """
        return self.match(job)

    def enrich_job(self, job: Any) -> Dict[str, Any]:
        """Return the complete job record with its matching result applied.

        ``match`` deliberately returns only normalized fields and scoring
        information.  Discovery callers also need source fields such as
        posting date, salary, and discovery time for storage and exports.
        This compatibility method preserves those fields while overlaying the
        scoring result.
        """
        job_data = self._to_dict(job)
        job_data.update(self.match(job))
        return job_data

    def _profile_list(self, field_name: str) -> List[str]:
        if self.resume_profile is None:
            return []

        if isinstance(self.resume_profile, dict):
            values = self.resume_profile.get(field_name, [])
        else:
            values = getattr(
                self.resume_profile,
                field_name,
                [],
            )

        if values is None:
            return []

        if isinstance(values, str):
            return [values]

        return [
            self._text(value)
            for value in values
            if self._text(value)
        ]

    def _get_preferred_locations(self) -> List[str]:
        locations = []

        locations.extend(
            self._profile_list("preferred_locations")
        )

        if not locations:
            locations.extend(
                [
                    "Hyderabad",
                    "Remote",
                    "Work from home",
                ]
            )

        return locations

    def _india_only(self) -> bool:
        return bool(self.matching_rules.get("india_only", True))

    def _has_excluded_domain(
        self,
        searchable_text: str,
        matched_industries: List[str],
    ) -> bool:
        excluded_domains = self.matching_rules.get(
            "excluded_domains",
            [],
        )
        matched_text = " ".join(matched_industries).lower()
        return any(
            str(domain).lower() in searchable_text
            and str(domain).lower() not in matched_text
            for domain in excluded_domains
        )

    @staticmethod
    def _is_india_eligible(
        location: str,
        searchable_text: str,
    ) -> bool:
        india_terms = {
            "india",
            "hyderabad",
            "bengaluru",
            "bangalore",
            "mumbai",
            "pune",
            "delhi",
            "gurugram",
            "gurgaon",
            "noida",
            "chennai",
            "kolkata",
            "remote india",
            "india remote",
            "work from home india",
            "pan india",
            "remote",
        }
        foreign_terms = {
            "united states",
            "usa",
            "u.s.",
            "canada",
            "uk",
            "united kingdom",
            "australia",
            "singapore",
            "new york",
            "california",
            "texas",
            "florida",
        }
        if any(term in location.lower() for term in foreign_terms):
            return False
        return any(term in searchable_text for term in india_terms)

    def _experience_rejection(
        self,
        job_data: Dict[str, Any],
        searchable_text: str,
    ) -> str:
        minimum = self._profile_number("experience_years_min")
        maximum = self._profile_number("experience_years_max")
        if minimum is None and maximum is None:
            return ""

        required_values = [
            int(value)
            for value in re.findall(
                r"(?<!\d)(\d{1,2})\s*\+?\s*(?:years?|yrs?)",
                searchable_text,
            )
        ]
        if not required_values:
            return ""

        required_minimum = min(required_values)
        required_maximum = max(required_values)
        if minimum is not None and required_maximum < minimum:
            return "Required experience is below the candidate range"
        if maximum is not None and required_minimum > maximum:
            return "Required experience exceeds the candidate range"
        return ""

    def _profile_number(self, field_name: str) -> float | None:
        if self.resume_profile is None:
            return None
        if isinstance(self.resume_profile, dict):
            value = self.resume_profile.get(field_name)
        else:
            value = getattr(self.resume_profile, field_name, None)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _score_rule(
        self,
        key: str,
        default: int,
    ) -> int:
        value = self.scoring_rules.get(key, default)

        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_dict(job: Any) -> Dict[str, Any]:
        if job is None:
            return {}

        if isinstance(job, dict):
            return job.copy()

        if is_dataclass(job):
            return asdict(job)

        if hasattr(job, "__dict__"):
            return vars(job).copy()

        return {}

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, list):
            return ", ".join(str(item) for item in value)

        return " ".join(str(value).split()).strip()

    @staticmethod
    def _contains_phrase(
        searchable_text: str,
        phrase: str,
    ) -> bool:
        normalized_phrase = " ".join(
            str(phrase).lower().split()
        ).strip()

        if not normalized_phrase:
            return False

        return normalized_phrase in searchable_text

    @classmethod
    def _matches_profile_term(
        cls,
        searchable_text: str,
        term: str,
        aliases: Dict[str, Any] | None = None,
    ) -> bool:
        candidates = [term]
        normalized_term = cls._normalize_phrase(term)

        if aliases:
            for key, values in aliases.items():
                if cls._normalize_phrase(key) == normalized_term:
                    if isinstance(values, str):
                        candidates.append(values)
                    elif isinstance(values, list):
                        candidates.extend(values)

        return any(
            cls._phrase_or_token_match(searchable_text, candidate)
            for candidate in candidates
        )

    @classmethod
    def _phrase_or_token_match(
        cls,
        searchable_text: str,
        phrase: Any,
    ) -> bool:
        normalized_phrase = cls._normalize_phrase(phrase)

        if not normalized_phrase:
            return False

        if normalized_phrase in searchable_text:
            return True

        phrase_tokens = cls._tokens(normalized_phrase)
        text_tokens = set(cls._tokens(searchable_text))

        if len(phrase_tokens) < 2:
            return False

        matched_tokens = sum(
            any(
                cls._token_starts_with(text_token, phrase_token)
                or cls._token_starts_with(phrase_token, text_token)
                for text_token in text_tokens
            )
            for phrase_token in phrase_tokens
        )

        return matched_tokens / len(phrase_tokens) >= 0.67

    @staticmethod
    def _normalize_phrase(value: Any) -> str:
        return " ".join(str(value or "").lower().split()).strip()

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return re.findall(r"[a-z0-9+#]+", value.lower())

    @staticmethod
    def _token_starts_with(left: str, right: str) -> bool:
        if len(left) < 4 or len(right) < 4:
            return left == right

        return left.startswith(right) or right.startswith(left)

    @staticmethod
    def _get_category(score: int) -> str:
        if score >= 75:
            return "Strong"
        if score >= 60:
            return "Good"
        if score >= 45:
            return "Review"
        return "Low"


if __name__ == "__main__":
    from src.resume_profile import load_resume_profile

    profile = load_resume_profile(
        "config/candidate_profile.yaml"
    )

    matcher = JobMatcher(
        resume_profile=profile,
        matching_rules={},
    )

    sample_job = {
        "title": "Business Analyst",
        "company": "Example Company",
        "location": "Hyderabad",
        "job_url": "https://example.com/job/123",
        "source": "Indeed",
        "description": (
            "Business analysis, SQL, stakeholder management, "
            "requirements gathering and UAT."
        ),
    }

    result = matcher.match(sample_job)

    print("Match result:")
    print(result)

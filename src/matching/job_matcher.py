from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from functools import lru_cache
from typing import Any

from src.config import MatchingRules, parse_matching_rules
from src.resume_profile import ResumeProfile, parse_resume_profile

INDIA_TERMS = (
    "india",
    "hyderabad",
    "secunderabad",
    "bengaluru",
    "bangalore",
    "mumbai",
    "navi mumbai",
    "pune",
    "delhi",
    "new delhi",
    "ncr",
    "gurugram",
    "gurgaon",
    "noida",
    "chennai",
    "kolkata",
    "ahmedabad",
    "kochi",
    "pan india",
)

FOREIGN_TERMS = (
    "united states",
    "usa",
    "u.s.",
    "canada",
    "uk",
    "united kingdom",
    "london",
    "australia",
    "singapore",
    "dubai",
    "uae",
    "new york",
    "california",
    "texas",
    "florida",
)

@lru_cache(maxsize=4096)
def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    # Whole-word match: "ai" must not match "maintain" or "Chennai",
    # "uat" must not match "evaluate". Hyphens and punctuation count as
    # boundaries, so "AI-powered" still matches "ai".
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")


def contains_phrase(text: str, phrase: Any) -> bool:
    """True when ``phrase`` appears in ``text`` as whole words."""
    normalized = " ".join(str(phrase or "").lower().split())
    if not normalized:
        return False
    return _phrase_pattern(normalized).search(text) is not None


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", value.lower())


def _token_matches(left: str, right: str) -> bool:
    # Short tokens must match exactly; longer ones may share a stem
    # ("gather" ~ "gathering", "requirement" ~ "requirements").
    if len(left) < 4 or len(right) < 4:
        return left == right
    return left.startswith(right) or right.startswith(left)


def fuzzy_phrase_match(text: str, phrase: Any, threshold: float = 0.67) -> bool:
    """
    Multi-word phrases also match when most of their words appear in any
    order, e.g. "Business requirements gathering" ~ "gather business
    requirements".
    """
    if contains_phrase(text, phrase):
        return True

    phrase_tokens = _tokens(str(phrase or ""))
    if len(phrase_tokens) < 2:
        return False

    text_tokens = set(_tokens(text))
    matched = sum(
        any(_token_matches(text_token, token) for text_token in text_tokens)
        for token in phrase_tokens
    )
    return matched / len(phrase_tokens) >= threshold


class JobMatcher:
    """
    Scores a job against the candidate profile with explainable reasons
    and hard eligibility gates. All weights and thresholds come from
    matching_rules.yaml.
    """

    def __init__(
        self,
        resume_profile: ResumeProfile | dict[str, Any] | None = None,
        matching_rules: MatchingRules | dict[str, Any] | None = None,
    ) -> None:
        self.profile = parse_resume_profile(resume_profile)
        self.rules = parse_matching_rules(matching_rules)
        self._aliases = {
            " ".join(key.lower().split()): values
            for key, values in self.rules.skill_aliases.items()
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match(self, job: Any) -> dict[str, Any]:
        """Return the score, category, reasons and gate results for a job."""
        job_data = self._to_dict(job)

        title = self._text(job_data.get("title"))
        location = self._text(job_data.get("location"))
        description = self._text(job_data.get("description"))
        company = self._text(job_data.get("company"))
        source = self._text(job_data.get("source")).lower()

        text = " ".join([title, company, location, description]).lower()
        # Evidence must come from the posting body, not just its title.
        body_text = description.lower()
        weights = self.rules.scoring

        score = 0
        reasons: list[str] = []
        missing_keywords: list[str] = []
        rejection_reasons: list[str] = []

        matched_roles = [
            role for role in self.profile.target_roles if contains_phrase(text, role)
        ]
        if matched_roles:
            score += weights.role_match
            reasons.append("Target role match: " + ", ".join(matched_roles))
        else:
            missing_keywords.extend(self.profile.target_roles[:3])

        evidence_groups = [
            (self.profile.proven_skills, weights.proven_skill, weights.proven_skill_max),
            (self.profile.responsibilities, weights.responsibility, weights.responsibility_max),
            (self.profile.tools_technologies, weights.tool, weights.tool_max),
            (self.profile.industries, weights.domain_match, weights.domain_match_max),
            (self.profile.experience_areas, weights.experience_area, weights.experience_area_max),
        ]

        evidence_terms: set[str] = set()
        matched_industries: list[str] = []
        for terms, weight, cap in evidence_groups:
            matched = [term for term in terms if self._matches_term(text, term)]
            score += min(len(matched) * weight, cap)
            reasons.extend(term for term in matched if term not in reasons)
            evidence_terms.update(
                term.lower() for term in matched if self._matches_term(body_text, term)
            )
            if terms is self.profile.industries:
                matched_industries = matched
        evidence_count = len(evidence_terms)

        matched_locations = [
            place
            for place in self.rules.preferred_locations
            if contains_phrase(location.lower(), place)
        ]
        if matched_locations:
            score += weights.preferred_location
            reasons.append("Preferred location: " + ", ".join(matched_locations))

        if self._has_excluded_domain(text, matched_industries):
            rejection_reasons.append("Job domain is outside the candidate profile")

        if self.rules.india_only and not self._is_india_eligible(location, text, source):
            rejection_reasons.append("Location is not India-eligible")

        if evidence_count < self.rules.minimum_evidence_matches:
            rejection_reasons.append("Insufficient resume evidence beyond the job title")

        experience_rejection = self._experience_rejection(job_data, text)
        if experience_rejection:
            rejection_reasons.append(experience_rejection)

        maximum = weights.maximum_score
        normalized_score = round(score / maximum * 100) if maximum else 0
        normalized_score = max(0, min(100, normalized_score))

        if normalized_score < self.rules.minimum_match_score:
            rejection_reasons.append("Match score is below the minimum threshold")

        return {
            "match_score": normalized_score,
            "match_category": self.category_for(normalized_score),
            "match_reasons": reasons,
            "missing_keywords": missing_keywords,
            "eligible": not rejection_reasons,
            "rejection_reasons": rejection_reasons,
            "evidence_count": evidence_count,
        }

    def score_job(self, job: Any) -> dict[str, Any]:
        """Backward-compatible alias for match()."""
        return self.match(job)

    def category_for(self, score: float) -> str:
        bands = self.rules.categories
        if score >= bands.strong:
            return "Strong"
        if score >= bands.good:
            return "Good"
        if score >= bands.review:
            return "Review"
        return "Low"

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def _matches_term(self, text: str, term: str) -> bool:
        candidates = [term, *self._aliases.get(" ".join(term.lower().split()), [])]
        return any(fuzzy_phrase_match(text, candidate) for candidate in candidates)

    def _has_excluded_domain(self, text: str, matched_industries: list[str]) -> bool:
        matched_text = " ".join(matched_industries).lower()
        return any(
            contains_phrase(text, domain) and domain.lower() not in matched_text
            for domain in self.rules.excluded_domains
        )

    def _is_india_eligible(self, location: str, text: str, source: str) -> bool:
        location_lower = location.lower()

        if any(contains_phrase(location_lower, term) for term in FOREIGN_TERMS):
            return False
        if any(contains_phrase(location_lower, term) for term in INDIA_TERMS):
            return True

        # A bare "Remote" (or empty) location is only accepted when the
        # posting ties the role to India, or it comes from an India portal.
        if source in self.rules.india_portals:
            return True
        return any(contains_phrase(text, term) for term in INDIA_TERMS)

    def _experience_rejection(self, job_data: dict[str, Any], text: str) -> str:
        candidate_min = self.profile.experience_years_min
        candidate_max = self.profile.experience_years_max
        if candidate_min is None and candidate_max is None:
            return ""

        required_min = job_data.get("experience_min")
        required_max = job_data.get("experience_max")

        if required_min is None and required_max is None:
            # No structured range from the portal: fall back to explicit
            # "N years" statements in the posting.
            values = [
                int(value)
                for value in re.findall(
                    r"(?<!\d)(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", text
                )
            ]
            if not values:
                return ""
            required_min, required_max = min(values), max(values)

        if candidate_min is not None and required_max is not None and required_max < candidate_min:
            return "Required experience is below the candidate range"
        if candidate_max is not None and required_min is not None and required_min > candidate_max:
            return "Required experience exceeds the candidate range"
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(job: Any) -> dict[str, Any]:
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

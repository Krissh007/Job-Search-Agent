from pathlib import Path

import pytest

from src.config import ConfigError, load_matching_rules, load_settings
from src.resume_profile import load_resume_profile, parse_resume_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config"


def test_repository_configs_are_valid():
    load_settings(CONFIG / "settings.yaml")
    load_matching_rules(CONFIG / "matching_rules.yaml")
    profile = load_resume_profile(CONFIG / "candidate_profile.yaml")
    assert "SQL" in profile.tools_technologies


def test_profile_accepts_legacy_tools_key_and_blank_years():
    profile = parse_resume_profile(
        {"tools_and_technologies": ["SQL"], "experience_years_min": ""}
    )
    assert profile.tools_technologies == ["SQL"]
    assert profile.experience_years_min is None


def test_profile_rejects_unknown_keys():
    with pytest.raises(ConfigError, match="target_role"):
        parse_resume_profile({"target_role": ["BA"]})


def test_profile_rejects_inverted_years():
    with pytest.raises(ConfigError):
        parse_resume_profile({"experience_years_min": 6, "experience_years_max": 3})


@pytest.mark.parametrize(
    "yaml_text, fragment",
    [
        ("search:\n  minimum_match_score: 40\n", "search.minimum_match_score"),
        ("browser:\n  reuse_existing_profile: true\n", "browser.reuse_existing_profile"),
        ("sources:\n  - monster\n", "Unknown sources"),
        ("search:\n  keywords: []\n", "keywords"),
    ],
)
def test_settings_reject_unknown_or_invalid_values(tmp_path, yaml_text, fragment):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ConfigError, match=fragment):
        load_settings(path)


def test_rules_reject_misplaced_gate(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("scoring:\n  minimum_evidence_matches: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="scoring.minimum_evidence_matches"):
        load_matching_rules(path)

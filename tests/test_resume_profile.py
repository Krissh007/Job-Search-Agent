from src.resume_profile import load_resume_profile


def main() -> None:
    profile = load_resume_profile()

    print("Resume profile loaded successfully.")
    print(f"Target roles: {len(profile.target_roles)}")
    print(f"Proven skills: {len(profile.proven_skills)}")
    print(f"Industries: {profile.industries}")
    print(f"Experience summary: {profile.experience_summary}")


if __name__ == "__main__":
    main()
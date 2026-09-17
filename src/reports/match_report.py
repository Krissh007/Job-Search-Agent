from pathlib import Path

from src.database import Database


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "books_test.db"


def main() -> None:
    database = Database(DATABASE_PATH)
    jobs = database.get_jobs()

    strong_jobs = [
        job
        for job in jobs
        if job["match_category"] in {"Strong", "Good"}
    ]

    print(
        f"Total records: {len(jobs)}"
    )

    print(
        f"Strong/Good matches: {len(strong_jobs)}"
    )

    if not strong_jobs:
        print("No Strong or Good matches found.")
        return

    print("\nMatching records:")

    for job in strong_jobs:
        print(
            f"- {job['title']} | "
            f"{job['company']} | "
            f"Score: {job['match_score']} | "
            f"Category: {job['match_category']}"
        )


if __name__ == "__main__":
    main()
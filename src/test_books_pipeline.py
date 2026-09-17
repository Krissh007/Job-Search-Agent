from pathlib import Path

from playwright.sync_api import sync_playwright

from src.database import Database
from src.matching.job_matcher import JobMatcher
from src.normalizer import JobNormalizer
from src.resume_profile import load_resume_profile
from src.sources.books_source import BooksSource


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "books_test.db"


def main() -> None:
    database = Database(DATABASE_PATH)
    normalizer = JobNormalizer()
    profile = load_resume_profile(PROJECT_ROOT)

    matcher = JobMatcher(
        profile,
        {
            "scoring": {
                "role_match": 40,
                "proven_skill": 3,
                "proven_skill_max": 30,
                "responsibility": 2,
                "responsibility_max": 20,
                "preferred_location": 10,
                "tool": 1,
                "tool_max": 10,
            }
        },
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False
        )

        page = browser.new_page()
        source = BooksSource(page)

        discovered_books = source.discover_jobs()

        print(
            f"Discovered records: {len(discovered_books)}"
        )

        for discovered_book in discovered_books:
            normalized_book = normalizer.normalize(
                discovered_book
            )

            job_data = {
                "job_url": normalized_book.job_url,
                "source": normalized_book.source,
                "title": normalized_book.title,
                "company": normalized_book.company,
                "location": normalized_book.location,
                "posted_date": normalized_book.posted_date,
                "description": normalized_book.description,
            }

            match_result = matcher.match(job_data)

            if database.job_exists(
                normalized_book.job_url
            ):
                database.update_job_match(
                    job_url=normalized_book.job_url,
                    match_score=match_result.score,
                    match_category=match_result.category,
                    match_reasons="; ".join(
                        match_result.reasons
                    ),
                    missing_keywords="; ".join(
                        match_result.missing_keywords
                    ),
                )

                print(
                    f"Updated existing record: "
                    f"{normalized_book.title} | "
                    f"Score: {match_result.score} | "
                    f"Category: {match_result.category}"
                )

                continue

            database.save_job(
                {
                    **job_data,
                    "match_score": match_result.score,
                    "match_category": match_result.category,
                    "match_reasons": "; ".join(
                        match_result.reasons
                    ),
                    "missing_keywords": "; ".join(
                        match_result.missing_keywords
                    ),
                    "status": "new",
                }
            )

            print(
                f"Saved new record: "
                f"{normalized_book.title} | "
                f"Score: {match_result.score} | "
                f"Category: {match_result.category}"
            )

        browser.close()

    saved_jobs = database.get_jobs()

    print(
        f"\nJobs in database: {len(saved_jobs)}"
    )


if __name__ == "__main__":
    main()
from src.discovery import DiscoveredJob
from src.normalizer import JobNormalizer


def main() -> None:
    job = DiscoveredJob(
        title="  AI   Business Analyst  ",
        company="  Example   Analytics ",
        location=" Hyderabad ",
        job_url="/jobs/123",
        source=" TEST ",
    )

    normalizer = JobNormalizer(
        base_url="https://example.com"
    )

    normalized_job = normalizer.normalize(job)

    print("Normalized job:")
    print(f"Title: {normalized_job.title}")
    print(f"Company: {normalized_job.company}")
    print(f"Location: {normalized_job.location}")
    print(f"URL: {normalized_job.job_url}")
    print(f"Source: {normalized_job.source}")


if __name__ == "__main__":
    main()
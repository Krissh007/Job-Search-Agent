from src.models import Job


def main() -> None:
    """Test the Job model."""

    job = Job(
        job_url="https://example.com/jobs/123",
        source="test",
        title="AI Business Analyst",
        company="Example Company",
        location="Hyderabad",
        match_score=85.0,
        match_category="Strong",
    )

    print("Job object created:")
    print(job)

    print("\nJob dictionary:")
    print(job.to_dict())

    print("\nModel test completed successfully.")


if __name__ == "__main__":
    main()
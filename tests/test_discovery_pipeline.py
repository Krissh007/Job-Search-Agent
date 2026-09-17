from pathlib import Path

from playwright.sync_api import sync_playwright

from src.pipelines.discovery_pipeline import DiscoveryPipeline


TEST_HTML = """
<html>
<body>
    <div class="job-card">
        <a href="https://example.com/jobs/1">
            <span class="job-title">AI Business Analyst</span>
        </a>

        <span class="company">Example Analytics</span>
        <span class="location">Hyderabad</span>

        <div class="job-description">
            Gather business requirements, write BRDs and user stories,
            coordinate UAT, work with stakeholders, and use SQL for
            product analytics in an AI-powered SaaS platform.
        </div>
    </div>

    <div class="job-card">
        <a href="https://example.com/jobs/2">
            <span class="job-title">Product Analyst</span>
        </a>

        <span class="company">Example SaaS</span>
        <span class="location">Remote</span>

        <div class="job-description">
            Analyze product metrics, collaborate with product managers,
            perform data analysis using SQL, and support customer insights.
        </div>
    </div>
</body>
</html>
"""


def test_discovery_pipeline():
    project_root = Path(__file__).resolve().parents[1]
    test_database = project_root / "data" / "test_pipeline.db"

    if test_database.exists():
        test_database.unlink()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(TEST_HTML)

        pipeline = DiscoveryPipeline(
            page=page,
            project_root=project_root,
            database_path=test_database,
        )

        saved_count = pipeline.run()

        assert saved_count == 2

        saved_jobs = pipeline.database.get_jobs()

        assert len(saved_jobs) == 2

        first_job = saved_jobs[0]
        second_job = saved_jobs[1]

        assert first_job["description"] != ""
        assert second_job["description"] != ""

        assert first_job["match_score"] is not None
        assert second_job["match_score"] is not None

        assert first_job["match_category"] is not None
        assert second_job["match_category"] is not None

        assert "Requirements Gathering" in first_job["match_reasons"]
        assert "UAT" in first_job["match_reasons"]
        assert "SQL" in first_job["match_reasons"]

        browser.close()
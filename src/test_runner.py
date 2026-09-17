from pathlib import Path

from playwright.sync_api import sync_playwright

from src.pipelines.discovery_pipeline import DiscoveryPipeline


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False
        )

        page = browser.new_page()

        page.goto(
            "https://books.toscrape.com/",
            wait_until="domcontentloaded",
        )

        print("Test page opened:")
        print(page.title())

        browser.close()


if __name__ == "__main__":
    main()
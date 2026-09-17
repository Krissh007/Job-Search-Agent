from dataclasses import dataclass

from playwright.sync_api import Page


@dataclass
class SourceJob:
    job_url: str
    source: str
    title: str
    company: str
    location: str
    posted_date: str
    description: str


class BooksSource:
    """Temporary source adapter used to test website extraction."""

    source_name = "books_test"

    def __init__(self, page: Page) -> None:
        self.page = page

    def discover_jobs(self) -> list[SourceJob]:
        self.page.goto(
            "https://books.toscrape.com/",
            wait_until="domcontentloaded",
        )

        jobs: list[SourceJob] = []

        books = self.page.locator("article.product_pod")

        for index in range(books.count()):
            book = books.nth(index)

            title = (
                book.locator("h3 a").get_attribute("title")
                or ""
            ).strip()

            relative_url = (
                book.locator("h3 a").get_attribute("href")
                or ""
            ).strip()

            job_url = self.page.url.rsplit("/", 1)[0] + "/" + relative_url

            price = book.locator(".price_color").inner_text().strip()

            jobs.append(
                SourceJob(
                    job_url=job_url,
                    source=self.source_name,
                    title=title,
                    company="Books to Scrape",
                    location="Remote",
                    posted_date="",
                    description=f"Book price: {price}",
                )
            )

        return jobs
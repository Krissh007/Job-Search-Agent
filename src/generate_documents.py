"""
Create tailored resumes and cover letters for jobs already in the database.

    python -m src.generate_documents               # every open job scoring >= 60 without documents
    python -m src.generate_documents --dry-run     # only list which jobs would get documents
    python -m src.generate_documents --min-score 70 --limit 5
    python -m src.generate_documents --job-url <url> --force   # redo one job
"""

from __future__ import annotations

import argparse
import logging

from src.database import Database
from src.pipelines.discovery_pipeline import (
    build_document_generator,
    configure_logging,
    load_context,
)
from src.reports.export_excel import export_master_jobs
from src.tailoring.generator import GenerationResult

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-score", type=int, help="Override tailoring.min_match_score")
    parser.add_argument("--limit", type=int, help="Override tailoring.max_jobs_per_run (0 = no limit)")
    parser.add_argument("--job-url", help="Only this job")
    parser.add_argument("--force", action="store_true", help="Regenerate even if documents exist")
    parser.add_argument("--dry-run", action="store_true", help="List the jobs that would be tailored")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    context = load_context()
    configure_logging(context)
    tailoring = context.settings.tailoring
    tailoring.enabled = True  # running this command is the opt-in
    if args.min_score is not None:
        tailoring.min_match_score = args.min_score
    if args.limit is not None:
        tailoring.max_jobs_per_run = args.limit

    with Database(context.database_path) as database:
        jobs = database.get_jobs()
        if args.job_url:
            jobs = [job for job in jobs if job["job_url"] == args.job_url]
            if not jobs:
                raise SystemExit(f"Job not found in database: {args.job_url}")
            if args.force:
                database.delete_tailored_documents(args.job_url)

        if args.dry_run:
            from src.tailoring.generator import DocumentGenerator

            done = set(database.get_tailored_documents())
            selector = DocumentGenerator.__new__(DocumentGenerator)
            selector.settings = tailoring
            result = GenerationResult()
            selected = selector.select_jobs(jobs, done, result)
            for job in selected:
                print(f"{job['match_score']:>5}  {job['title']} | {job['company']}")
            print(f"\n{len(selected)} job(s) would be tailored; already done {result.already_done}, "
                  f"below {tailoring.min_match_score}: {result.below_threshold}, "
                  f"no description: {result.no_description}, over limit: {result.deferred}")
            return

        generator = build_document_generator(context)
        if generator is None:
            raise SystemExit("Tailoring is not set up; see the warning above.")
        result = generator.generate(database, jobs)
        result.log_summary()

    export_master_jobs(context.database_path, context.export_directory)
    print(f"Created documents for {len(result.created)} job(s) in {generator.output_directory}")


if __name__ == "__main__":
    main()

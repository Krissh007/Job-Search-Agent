"""
One command for Windows Task Scheduler.

    python -m src.daily            # morning: search + tailor + sync, then auto-apply
    python -m src.daily --apply    # afternoon: pick up Claude's shortlist, auto-apply, sync

Each stage is isolated: a failed search still lets auto-apply and the
project sync run.
"""

from __future__ import annotations

import argparse
import logging

from src.database import Database
from src.pipelines import discovery_pipeline
from src.project_sync import export_snapshot, import_updates, sync_directory

logger = logging.getLogger("src.daily")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Skip the search; only sync and auto-apply")
    args = parser.parse_args(argv)

    context = discovery_pipeline.load_context()
    discovery_pipeline.configure_logging(context)
    out_dir = sync_directory(context.project_root)

    try:
        with Database(context.database_path) as database:
            import_updates(database, out_dir)
    except Exception:
        logger.exception("Importing Claude's updates failed")

    if not args.apply:
        try:
            discovery_pipeline.run(context)
        except Exception:
            logger.exception("Search pipeline failed; continuing to auto-apply")

    try:
        from src.apply import auto_apply

        auto_apply.run(context)
    except Exception:
        logger.exception("Auto-apply failed")

    try:
        with Database(context.database_path) as database:
            export_snapshot(database, out_dir)
    except Exception:
        logger.exception("Project sync export failed")


if __name__ == "__main__":
    main()

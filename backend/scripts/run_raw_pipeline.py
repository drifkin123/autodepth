"""Run raw-page pipeline maintenance commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import async_session_factory
from app.services.artifacts import get_artifact_store
from app.services.bat_raw_pipeline import parse_bat_raw_page
from app.services.bat_raw_seed import seed_bat_raw_targets


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed-bat")
    seed_parser.add_argument(
        "--target-source",
        choices=("models", "makes"),
        default="models",
    )
    seed_parser.add_argument("--selected-key", action="append")

    reparse_parser = subparsers.add_parser("reparse-bat")
    reparse_parser.add_argument("--raw-page-id", required=True)

    return parser.parse_args(argv)


async def main(
    *,
    command: str,
    target_source: str = "models",
    selected_key: list[str] | None = None,
    raw_page_id: str | None = None,
) -> dict:
    async with async_session_factory() as session:
        if command == "seed-bat":
            return await seed_bat_raw_targets(
                session,
                target_source=target_source,
                selected_keys=set(selected_key) if selected_key else None,
            )
        if command == "reparse-bat":
            if raw_page_id is None:
                raise ValueError("raw_page_id is required for reparse-bat")
            outcome = await parse_bat_raw_page(
                session,
                artifact_store=get_artifact_store(),
                raw_page_id=uuid.UUID(raw_page_id),
            )
            return {
                "lots_found": outcome.lots_found,
                "lots_inserted": outcome.lots_inserted,
                "lots_updated": outcome.lots_updated,
                "targets_discovered": outcome.targets_discovered,
            }
    raise ValueError(f"Unknown command: {command}")


if __name__ == "__main__":
    args = parse_args()
    result = asyncio.run(
        main(
            command=args.command,
            target_source=getattr(args, "target_source", "models"),
            selected_key=getattr(args, "selected_key", None),
            raw_page_id=getattr(args, "raw_page_id", None),
        )
    )
    print(json.dumps(result, sort_keys=True))

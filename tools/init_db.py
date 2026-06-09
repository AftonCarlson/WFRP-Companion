from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.config import load_config
from wfrp_companion.db.connection import initialize_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize the local WFRP Companion SQLite database."
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite database path. Defaults to WFRP_DB_PATH or data/wfrp_companion.sqlite.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    db_path = args.db_path or config.db_path

    with initialize_database(db_path):
        pass

    print(f"Initialized WFRP Companion database at {db_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

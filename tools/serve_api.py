from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Sequence

import uvicorn
from fastapi import FastAPI

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pragma: no cover

from wfrp_companion.api.app import create_app
from wfrp_companion.config import AppConfig, load_config


ServerRunner = Callable[[FastAPI, str, int], None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the local WFRP Companion API.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind. Defaults to 127.0.0.1 for local-only serving.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind. Defaults to 8000.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Private app data directory. Defaults to WFRP_DATA_DIR or data/.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="SQLite database path. Defaults to WFRP_DB_PATH or <data-dir>/wfrp_companion.sqlite.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> AppConfig:
    config = load_config()
    data_dir = args.data_dir or config.data_dir
    db_path = args.db_path or (
        data_dir / "wfrp_companion.sqlite" if args.data_dir else config.db_path
    )
    return AppConfig(
        pdf_root=config.pdf_root,
        data_dir=data_dir,
        db_path=db_path,
        asset_dir=config.asset_dir,
        openai_api_key=config.openai_api_key,
        openai_model=config.openai_model,
        openai_timeout_seconds=config.openai_timeout_seconds,
        chat_context_hit_limit=config.chat_context_hit_limit,
        chat_context_char_limit=config.chat_context_char_limit,
        chat_context_window_chars=config.chat_context_window_chars,
        chat_prompt_history_turn_limit=config.chat_prompt_history_turn_limit,
        chat_prompt_history_char_limit=config.chat_prompt_history_char_limit,
        chat_retrieval_history_turn_limit=config.chat_retrieval_history_turn_limit,
        chat_retrieval_query_char_limit=config.chat_retrieval_query_char_limit,
        embedding_provider=config.embedding_provider,
        embedding_model=config.embedding_model,
        embedding_dimensions=config.embedding_dimensions,
    )


def run_uvicorn(app: FastAPI, host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port)


def main(
    argv: Sequence[str] | None = None,
    *,
    run_server: ServerRunner = run_uvicorn,
) -> int:
    args = build_parser().parse_args(argv)
    app = create_app(config_from_args(args))
    run_server(app, args.host, args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_PDF_ROOT = Path("/Users/aftoncarlson/TTRPGs/WFRP 2e")


@dataclass(frozen=True)
class AppConfig:
    pdf_root: Path
    data_dir: Path
    db_path: Path
    asset_dir: Path
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_timeout_seconds: float = 60.0
    chat_context_hit_limit: int = 6
    chat_context_char_limit: int = 9000
    chat_context_window_chars: int = 1600
    chat_prompt_history_turn_limit: int = 6
    chat_prompt_history_char_limit: int = 2500
    chat_retrieval_history_turn_limit: int = 3
    chat_retrieval_query_char_limit: int = 900
    embedding_provider: str = "disabled"
    embedding_model: str = "local-hash-v1"
    embedding_dimensions: int = 64


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(
    *,
    environ: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> AppConfig:
    source = os.environ if environ is None else environ
    root = project_root() if repo_root is None else repo_root
    data_dir = Path(source.get("WFRP_DATA_DIR", root / "data"))

    return AppConfig(
        pdf_root=Path(source.get("WFRP_PDF_ROOT", DEFAULT_PDF_ROOT)),
        data_dir=data_dir,
        db_path=Path(source.get("WFRP_DB_PATH", data_dir / "wfrp_companion.sqlite")),
        asset_dir=Path(
            source.get("WFRP_ASSET_DIR", data_dir / "library" / "assets")
        ),
        openai_api_key=source.get("OPENAI_API_KEY"),
        openai_model=source.get("WFRP_OPENAI_MODEL", "gpt-5.4-mini"),
        openai_timeout_seconds=float(source.get("WFRP_OPENAI_TIMEOUT_SECONDS", "60")),
        chat_context_hit_limit=int(source.get("WFRP_CHAT_CONTEXT_HIT_LIMIT", "6")),
        chat_context_char_limit=int(source.get("WFRP_CHAT_CONTEXT_CHAR_LIMIT", "9000")),
        chat_context_window_chars=int(source.get("WFRP_CHAT_CONTEXT_WINDOW_CHARS", "1600")),
        chat_prompt_history_turn_limit=int(
            source.get("WFRP_CHAT_PROMPT_HISTORY_TURN_LIMIT", "6")
        ),
        chat_prompt_history_char_limit=int(
            source.get("WFRP_CHAT_PROMPT_HISTORY_CHAR_LIMIT", "2500")
        ),
        chat_retrieval_history_turn_limit=int(
            source.get("WFRP_CHAT_RETRIEVAL_HISTORY_TURN_LIMIT", "3")
        ),
        chat_retrieval_query_char_limit=int(
            source.get("WFRP_CHAT_RETRIEVAL_QUERY_CHAR_LIMIT", "900")
        ),
        embedding_provider=source.get("WFRP_EMBEDDING_PROVIDER", "disabled"),
        embedding_model=source.get("WFRP_EMBEDDING_MODEL", "local-hash-v1"),
        embedding_dimensions=int(source.get("WFRP_EMBEDDING_DIMENSIONS", "64")),
    )

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
    )

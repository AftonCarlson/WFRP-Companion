from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def managed_pdf_path(data_dir: Path, book_id: str, source_sha256: str) -> Path:
    return (
        data_dir.expanduser().resolve()
        / "library"
        / "pdfs"
        / book_id
        / f"source-{source_sha256}.pdf"
    )


def copy_pdf_atomic(source_path: Path, target_path: Path) -> str:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f"{target_path.name}.tmp-{os.getpid()}")

    try:
        with source_path.open("rb") as source, temp_path.open("wb") as target:
            shutil.copyfileobj(source, target, length=CHUNK_SIZE)
        managed_sha = sha256_file(temp_path)
        os.replace(temp_path, target_path)
        return managed_sha
    finally:
        temp_path.unlink(missing_ok=True)


def managed_file_matches(path: Path, expected_sha256: str) -> bool:
    return path.exists() and sha256_file(path) == expected_sha256

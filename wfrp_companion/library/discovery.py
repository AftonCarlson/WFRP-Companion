from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wfrp_companion.library.identity import (
    book_id_for,
    category_for,
    folder_id_for,
    path_to_posix,
    relative_pdf_path,
)


@dataclass(frozen=True)
class PdfCandidate:
    source_path: Path
    relative_path: Path
    relative_path_posix: str
    book_id: str
    title: str
    category: str
    folder_relative_path: Path
    folder_id: str


def find_pdf_paths(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda path: path_to_posix(relative_pdf_path(root, path)).casefold(),
    )


def discover_pdfs(root: Path) -> list[PdfCandidate]:
    candidates: list[PdfCandidate] = []
    for source_path in find_pdf_paths(root):
        relative_path = relative_pdf_path(root, source_path)
        folder_relative_path = relative_path.parent
        candidates.append(
            PdfCandidate(
                source_path=source_path,
                relative_path=relative_path,
                relative_path_posix=path_to_posix(relative_path),
                book_id=book_id_for(root, source_path),
                title=source_path.stem,
                category=category_for(relative_path),
                folder_relative_path=folder_relative_path,
                folder_id=folder_id_for(folder_relative_path),
            )
        )
    return candidates

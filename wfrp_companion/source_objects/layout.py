from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LayoutPage:
    page_number: int
    has_word_geometry: bool
    word_count: int
    block_count: int


def load_pdf_layout_pages(pdf_path: Path, *, page_count: int) -> tuple[LayoutPage, ...]:
    if not pdf_path.exists():
        return ()

    try:
        document = open_pdf_document(pdf_path)
    except Exception:  # noqa: BLE001
        return ()
    try:
        bounded_count = min(page_count, len(document))
        pages: list[LayoutPage] = []
        for index in range(bounded_count):
            page = document[index]
            words = page.get_text("words") or []
            blocks = page.get_text("blocks") or []
            pages.append(
                LayoutPage(
                    page_number=index + 1,
                    has_word_geometry=bool(words),
                    word_count=len(words),
                    block_count=len(blocks),
                )
            )
        return tuple(pages)
    finally:
        document.close()


def open_pdf_document(pdf_path: Path) -> Any:
    try:
        import pymupdf
    except ModuleNotFoundError:  # pragma: no cover - compatibility fallback
        import fitz as pymupdf  # type: ignore[no-redef]

    return pymupdf.open(pdf_path)

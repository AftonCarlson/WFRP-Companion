"""Audit local PDF extraction quality without saving book text.

The output intentionally contains only numeric/page metadata. It does not
persist extracted WFRP book text.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import fitz


LOW_TEXT_CHARS = 100
MIN_USEFUL_TEXT_CHARS = 500


@dataclass
class PageStats:
    page_number: int
    text_chars: int
    word_count: int
    image_count: int
    low_text: bool
    likely_ocr_needed: bool


@dataclass
class PdfStats:
    path: str
    title: str
    category: str
    file_size_bytes: int
    page_count: int
    pages_with_text: int
    zero_text_pages: int
    low_text_pages: int
    likely_ocr_pages: int
    total_text_chars: int
    total_words: int
    total_images: int
    avg_text_chars_per_page: float
    median_text_chars_per_page: float
    min_text_chars_on_page: int
    max_text_chars_on_page: int
    extraction_health: str
    pages: list[PageStats]
    error: str | None = None


def find_pdfs(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def infer_category(root: Path, pdf_path: Path) -> str:
    try:
        relative = pdf_path.relative_to(root)
    except ValueError:
        return ""
    return relative.parts[0] if len(relative.parts) > 1 else ""


def health_for(page_count: int, pages_with_text: int, low_text_pages: int) -> str:
    if page_count == 0:
        return "empty"

    text_ratio = pages_with_text / page_count
    low_text_ratio = low_text_pages / page_count

    if text_ratio >= 0.95 and low_text_ratio <= 0.15:
        return "good"
    if text_ratio >= 0.80 and low_text_ratio <= 0.35:
        return "mixed"
    return "needs-review"


def audit_pdf(root: Path, pdf_path: Path) -> PdfStats:
    title = pdf_path.stem
    category = infer_category(root, pdf_path)
    file_size = pdf_path.stat().st_size

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:  # noqa: BLE001
        return PdfStats(
            path=str(pdf_path),
            title=title,
            category=category,
            file_size_bytes=file_size,
            page_count=0,
            pages_with_text=0,
            zero_text_pages=0,
            low_text_pages=0,
            likely_ocr_pages=0,
            total_text_chars=0,
            total_words=0,
            total_images=0,
            avg_text_chars_per_page=0.0,
            median_text_chars_per_page=0.0,
            min_text_chars_on_page=0,
            max_text_chars_on_page=0,
            extraction_health="error",
            pages=[],
            error=f"{type(exc).__name__}: {exc}",
        )

    page_stats: list[PageStats] = []

    with document:
        for page_index, page in enumerate(document):
            text = page.get_text("text") or ""
            text_chars = len(text.strip())
            word_count = len(text.split())
            image_count = len(page.get_images(full=True))
            low_text = text_chars < LOW_TEXT_CHARS
            likely_ocr_needed = low_text and image_count > 0

            page_stats.append(
                PageStats(
                    page_number=page_index + 1,
                    text_chars=text_chars,
                    word_count=word_count,
                    image_count=image_count,
                    low_text=low_text,
                    likely_ocr_needed=likely_ocr_needed,
                )
            )

    text_counts = [page.text_chars for page in page_stats]
    page_count = len(page_stats)
    pages_with_text = sum(1 for count in text_counts if count > 0)
    zero_text_pages = sum(1 for count in text_counts if count == 0)
    low_text_pages = sum(1 for count in text_counts if count < LOW_TEXT_CHARS)
    likely_ocr_pages = sum(1 for page in page_stats if page.likely_ocr_needed)
    total_text_chars = sum(text_counts)
    total_words = sum(page.word_count for page in page_stats)
    total_images = sum(page.image_count for page in page_stats)

    return PdfStats(
        path=str(pdf_path),
        title=title,
        category=category,
        file_size_bytes=file_size,
        page_count=page_count,
        pages_with_text=pages_with_text,
        zero_text_pages=zero_text_pages,
        low_text_pages=low_text_pages,
        likely_ocr_pages=likely_ocr_pages,
        total_text_chars=total_text_chars,
        total_words=total_words,
        total_images=total_images,
        avg_text_chars_per_page=round(total_text_chars / page_count, 2)
        if page_count
        else 0.0,
        median_text_chars_per_page=round(statistics.median(text_counts), 2)
        if text_counts
        else 0.0,
        min_text_chars_on_page=min(text_counts) if text_counts else 0,
        max_text_chars_on_page=max(text_counts) if text_counts else 0,
        extraction_health=health_for(page_count, pages_with_text, low_text_pages),
        pages=page_stats,
    )


def write_json(output_path: Path, root: Path, stats: Iterable[PdfStats]) -> None:
    stats_list = list(stats)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "low_text_chars_threshold": LOW_TEXT_CHARS,
        "min_useful_text_chars_reference": MIN_USEFUL_TEXT_CHARS,
        "note": "Numeric extraction audit only; no extracted book text is stored.",
        "books": [
            {
                **{
                    key: value
                    for key, value in asdict(book).items()
                    if key != "pages"
                },
                "pages": [asdict(page) for page in book.pages],
            }
            for book in stats_list
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_csv(output_path: Path, stats: Iterable[PdfStats]) -> None:
    fieldnames = [
        "category",
        "title",
        "page_count",
        "pages_with_text",
        "zero_text_pages",
        "low_text_pages",
        "likely_ocr_pages",
        "total_words",
        "total_images",
        "avg_text_chars_per_page",
        "median_text_chars_per_page",
        "extraction_health",
        "path",
        "error",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for book in stats:
            row = {field: getattr(book, field) for field in fieldnames}
            writer.writerow(row)


def print_summary(stats: list[PdfStats]) -> None:
    total_books = len(stats)
    total_pages = sum(book.page_count for book in stats)
    total_ocr_pages = sum(book.likely_ocr_pages for book in stats)
    total_low_text_pages = sum(book.low_text_pages for book in stats)
    health_counts: dict[str, int] = {}
    for book in stats:
        health_counts[book.extraction_health] = (
            health_counts.get(book.extraction_health, 0) + 1
        )

    print("PDF extraction audit")
    print(f"Books: {total_books}")
    print(f"Pages: {total_pages}")
    print(f"Low-text pages: {total_low_text_pages}")
    print(f"Likely OCR-needed pages: {total_ocr_pages}")
    print("Health:", ", ".join(f"{key}={value}" for key, value in sorted(health_counts.items())))
    print()
    print("Books needing review:")
    needing_review = [
        book
        for book in stats
        if book.extraction_health in {"mixed", "needs-review", "error"}
    ]
    if not needing_review:
        print("- None")
        return

    for book in needing_review:
        print(
            f"- {book.title}: {book.extraction_health}; "
            f"pages={book.page_count}; low_text={book.low_text_pages}; "
            f"likely_ocr={book.likely_ocr_pages}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        type=Path,
        help="Root folder containing PDFs to audit.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("data/audits/pdf_extraction_audit.json"),
        help="Path for the JSON audit output.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("data/audits/pdf_extraction_audit.csv"),
        help="Path for the CSV summary output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()

    if not root.exists():
        raise SystemExit(f"Root path does not exist: {root}")

    pdfs = find_pdfs(root)
    if not pdfs:
        raise SystemExit(f"No PDFs found under: {root}")

    stats = [audit_pdf(root, pdf_path) for pdf_path in pdfs]
    write_json(args.json, root, stats)
    write_csv(args.csv, stats)
    print_summary(stats)
    print()
    print(f"Wrote JSON: {args.json}")
    print(f"Wrote CSV: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

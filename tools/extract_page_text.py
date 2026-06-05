"""Extract one text reference per PDF page, using OCR when needed.

Outputs are private local derived data under `data/page_text/` by default and
must not be committed. Each book gets one JSON file containing page records with
source path, page number, extraction method, basic counts, and text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import fitz


LOW_TEXT_CHARS = 100
DEFAULT_DPI = 200


@dataclass
class PageText:
    page_number: int
    page_label: str | None
    text: str
    extraction_method: str
    embedded_text_chars: int
    text_chars: int
    word_count: int
    image_count: int
    ocr_attempted: bool
    ocr_error: str | None


@dataclass
class BookText:
    book_id: str
    title: str
    category: str
    source_path: str
    source_sha256: str
    page_count: int
    generated_at: str
    ocr_language: str
    ocr_dpi: int
    low_text_chars_threshold: int
    pages: list[PageText]


def find_pdfs(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "book"


def book_id_for(root: Path, pdf_path: Path) -> str:
    try:
        relative = pdf_path.relative_to(root)
    except ValueError:
        relative = Path(pdf_path.name)
    return slugify(str(relative.with_suffix("")))


def infer_category(root: Path, pdf_path: Path) -> str:
    try:
        relative = pdf_path.relative_to(root)
    except ValueError:
        return ""
    return relative.parts[0] if len(relative.parts) > 1 else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    normalized_lines: list[str] = []
    blank_seen = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if not blank_seen:
                normalized_lines.append("")
            blank_seen = True
            continue
        normalized_lines.append(stripped)
        blank_seen = False

    return "\n".join(normalized_lines).strip()


def normalize_page_label(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def extract_ocr_text(page: fitz.Page, language: str, dpi: int) -> str:
    try:
        text_page = page.get_textpage_ocr(language=language, dpi=dpi)
        return page.get_text("text", textpage=text_page)
    except Exception as exc:  # noqa: BLE001
        if "No OCR support in this build" not in str(exc):
            raise

    with tempfile.TemporaryDirectory(prefix="wfrp-ocr-") as temp_dir:
        image_path = Path(temp_dir) / f"page-{page.number + 1}.png"
        pixmap = page.get_pixmap(dpi=dpi)
        pixmap.save(image_path)
        completed = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", language, "--dpi", str(dpi)],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout


def extract_page_text(
    page: fitz.Page,
    *,
    language: str,
    dpi: int,
    force_ocr: bool,
    low_text_chars: int,
) -> PageText:
    embedded_text = normalize_text(page.get_text("text") or "")
    embedded_text_chars = len(embedded_text)
    image_count = len(page.get_images(full=True))
    should_ocr = force_ocr or embedded_text_chars < low_text_chars
    ocr_attempted = False
    ocr_error = None
    extraction_method = "embedded"
    text = embedded_text

    if should_ocr:
        ocr_attempted = True
        try:
            ocr_text = normalize_text(extract_ocr_text(page, language, dpi))
            if ocr_text:
                text = ocr_text
                extraction_method = "ocr"
            else:
                extraction_method = "ocr-empty"
        except Exception as exc:  # noqa: BLE001
            ocr_error = f"{type(exc).__name__}: {exc}"
            extraction_method = "ocr-error" if not embedded_text else "embedded"

    return PageText(
        page_number=page.number + 1,
        page_label=normalize_page_label(page.get_label()),
        text=text,
        extraction_method=extraction_method,
        embedded_text_chars=embedded_text_chars,
        text_chars=len(text),
        word_count=len(text.split()),
        image_count=image_count,
        ocr_attempted=ocr_attempted,
        ocr_error=ocr_error,
    )


def selected_page_indexes(
    page_count: int,
    *,
    page_limit: int | None,
    page_range: str | None,
) -> list[int]:
    if page_range:
        start_text, _, end_text = page_range.partition("-")
        start = int(start_text)
        end = int(end_text) if end_text else start
        if start < 1 or end < start:
            raise ValueError(f"Invalid page range: {page_range}")
        return list(range(start - 1, min(end, page_count)))

    end = page_count if page_limit is None else min(page_limit, page_count)
    return list(range(end))


def extract_book(
    root: Path,
    pdf_path: Path,
    *,
    language: str,
    dpi: int,
    force_ocr: bool,
    low_text_chars: int,
    page_limit: int | None,
    page_range: str | None,
    progress_every: int,
) -> BookText:
    document = fitz.open(pdf_path)
    with document:
        indexes = selected_page_indexes(
            document.page_count,
            page_limit=page_limit,
            page_range=page_range,
        )
        pages: list[PageText] = []
        for position, index in enumerate(indexes, start=1):
            pages.append(
                extract_page_text(
                    document[index],
                    language=language,
                    dpi=dpi,
                    force_ocr=force_ocr,
                    low_text_chars=low_text_chars,
                )
            )
            if progress_every > 0 and position % progress_every == 0:
                print(
                    f"  processed {position}/{len(indexes)} pages "
                    f"({pdf_path.name})"
                )

        if (
            indexes
            and progress_every > 0
            and len(indexes) % progress_every != 0
        ):
            print(
                f"  processed {len(indexes)}/{len(indexes)} pages "
                f"({pdf_path.name})"
            )

        return BookText(
            book_id=book_id_for(root, pdf_path),
            title=pdf_path.stem,
            category=infer_category(root, pdf_path),
            source_path=str(pdf_path),
            source_sha256=sha256_file(pdf_path),
            page_count=document.page_count,
            generated_at=datetime.now(timezone.utc).isoformat(),
            ocr_language=language,
            ocr_dpi=dpi,
            low_text_chars_threshold=low_text_chars,
            pages=pages,
        )


def write_book_text(output_root: Path, book: BookText) -> Path:
    output_path = output_root / f"{book.book_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(book), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


def print_summary(books: list[BookText]) -> None:
    total_pages = sum(len(book.pages) for book in books)
    total_chars = sum(page.text_chars for book in books for page in book.pages)
    methods: dict[str, int] = {}
    errors = 0

    for book in books:
        for page in book.pages:
            methods[page.extraction_method] = (
                methods.get(page.extraction_method, 0) + 1
            )
            if page.ocr_error:
                errors += 1

    print("Page text extraction")
    print(f"Books processed: {len(books)}")
    print(f"Pages written: {total_pages}")
    print(f"Characters written: {total_chars}")
    print("Methods:", ", ".join(f"{key}={value}" for key, value in sorted(methods.items())))
    print(f"OCR errors: {errors}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Root folder containing PDFs.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/page_text"),
        help="Output directory for page-level text JSON files.",
    )
    parser.add_argument(
        "--book",
        help="Only process PDFs whose filename contains this case-insensitive text.",
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        help="Only process the first N pages of each selected PDF.",
    )
    parser.add_argument(
        "--page-range",
        help="Only process a 1-based inclusive page range, for example 1-5.",
    )
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="OCR every page, even when embedded text is available.",
    )
    parser.add_argument(
        "--language",
        default="eng",
        help="Tesseract language code. Default: eng.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"OCR render DPI. Default: {DEFAULT_DPI}.",
    )
    parser.add_argument(
        "--low-text-chars",
        type=int,
        default=LOW_TEXT_CHARS,
        help=f"OCR pages below this embedded text character count. Default: {LOW_TEXT_CHARS}.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing book JSON outputs.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Print progress after this many pages. Use 0 to disable.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    output_root = args.output

    if not root.exists():
        raise SystemExit(f"Root path does not exist: {root}")

    pdfs = find_pdfs(root)
    if args.book:
        needle = args.book.casefold()
        pdfs = [path for path in pdfs if needle in path.name.casefold()]

    if not pdfs:
        raise SystemExit("No matching PDFs found.")

    books: list[BookText] = []
    for pdf_path in pdfs:
        book_id = book_id_for(root, pdf_path)
        output_path = output_root / f"{book_id}.json"
        if output_path.exists() and not args.overwrite:
            print(f"Skipping existing output: {output_path}")
            continue

        print(f"Extracting: {pdf_path.name}")
        book = extract_book(
            root,
            pdf_path,
            language=args.language,
            dpi=args.dpi,
            force_ocr=args.force_ocr,
            low_text_chars=args.low_text_chars,
            page_limit=args.page_limit,
            page_range=args.page_range,
            progress_every=args.progress_every,
        )
        written = write_book_text(output_root, book)
        print(f"Wrote: {written}")
        books.append(book)

    print()
    print_summary(books)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

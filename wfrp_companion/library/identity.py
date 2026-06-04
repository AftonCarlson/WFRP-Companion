from __future__ import annotations

import hashlib
import re
from pathlib import Path


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "book"


def path_to_posix(path: Path) -> str:
    text = path.as_posix()
    return "" if text == "." else text


def relative_pdf_path(root: Path, pdf_path: Path) -> Path:
    try:
        return pdf_path.relative_to(root)
    except ValueError:
        return Path(pdf_path.name)


def book_id_for(root: Path, pdf_path: Path) -> str:
    return slugify(str(relative_pdf_path(root, pdf_path).with_suffix("")))


def folder_id_for(relative_folder: Path) -> str:
    posix_path = path_to_posix(relative_folder)
    if not posix_path:
        return "root"

    digest = hashlib.sha1(posix_path.encode("utf-8")).hexdigest()[:8]
    return f"folder-{slugify(posix_path)}-{digest}"


def category_for(relative_path: Path) -> str:
    return relative_path.parts[0] if len(relative_path.parts) > 1 else ""

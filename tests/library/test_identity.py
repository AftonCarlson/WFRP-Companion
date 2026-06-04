from __future__ import annotations

import hashlib
from pathlib import Path

from tools.extract_page_text import book_id_for as extraction_book_id_for

from wfrp_companion.library.identity import (
    book_id_for,
    category_for,
    folder_id_for,
    path_to_posix,
    relative_pdf_path,
    slugify,
)


def test_slugify_matches_existing_extraction_convention() -> None:
    assert slugify("WFRP 2e: GM's Toolkit") == "wfrp-2e-gm-s-toolkit"
    assert slugify("Paths of the Damned/Ashes of Middenheim") == (
        "paths-of-the-damned-ashes-of-middenheim"
    )
    assert slugify("!!!") == "book"


def test_book_id_matches_page_text_extraction_tool(tmp_path: Path) -> None:
    root = tmp_path / "WFRP 2e"
    pdf_path = (
        root
        / "Adventure Modules and Campaigns"
        / "Paths of the Damned"
        / "Ashes of Middenheim.pdf"
    )

    assert book_id_for(root, pdf_path) == extraction_book_id_for(root, pdf_path)
    assert book_id_for(root, pdf_path) == (
        "adventure-modules-and-campaigns-paths-of-the-damned-ashes-of-middenheim"
    )


def test_relative_pdf_path_and_posix_text_are_source_root_relative(
    tmp_path: Path,
) -> None:
    root = tmp_path / "WFRP 2e"
    pdf_path = root / "Core Book & GM Essentials" / "Core Rulebook.PDF"

    relative_path = relative_pdf_path(root, pdf_path)

    assert relative_path == Path("Core Book & GM Essentials") / "Core Rulebook.PDF"
    assert path_to_posix(relative_path) == (
        "Core Book & GM Essentials/Core Rulebook.PDF"
    )


def test_relative_pdf_path_falls_back_to_filename_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "WFRP 2e"
    outside = tmp_path / "Elsewhere" / "Loose Book.pdf"

    assert relative_pdf_path(root, outside) == Path("Loose Book.pdf")


def test_category_is_first_folder_segment() -> None:
    assert category_for(Path("Core Book & GM Essentials") / "Core Rulebook.pdf") == (
        "Core Book & GM Essentials"
    )
    assert category_for(Path("Loose Book.pdf")) == ""


def test_folder_ids_are_hash_suffixed_to_avoid_slug_collisions() -> None:
    plus_folder = Path("Rules+A")
    space_folder = Path("Rules A")

    plus_expected_hash = hashlib.sha1(b"Rules+A").hexdigest()[:8]
    space_expected_hash = hashlib.sha1(b"Rules A").hexdigest()[:8]

    assert folder_id_for(Path(".")) == "root"
    assert folder_id_for(Path("")) == "root"
    assert folder_id_for(plus_folder) == f"folder-rules-a-{plus_expected_hash}"
    assert folder_id_for(space_folder) == f"folder-rules-a-{space_expected_hash}"
    assert folder_id_for(plus_folder) != folder_id_for(space_folder)

from __future__ import annotations

from pathlib import Path

from wfrp_companion.library.discovery import discover_pdfs, find_pdf_paths
from wfrp_companion.library.identity import folder_id_for


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n")
    return path


def test_find_pdf_paths_recurses_and_accepts_pdf_suffix_case(
    tmp_path: Path,
) -> None:
    root = tmp_path / "WFRP 2e"
    ashes = touch(root / "Adventure Modules" / "Ashes.pdf")
    core = touch(root / "Core" / "Core Rulebook.PDF")
    touch(root / "Core" / "notes.txt")

    assert find_pdf_paths(root) == [ashes, core]


def test_discover_pdfs_returns_sorted_candidates_with_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "WFRP 2e"
    later = touch(root / "World Guides" / "Sigmar's Heirs.pdf")
    earlier = touch(
        root
        / "Adventure Modules and Campaigns"
        / "Paths of the Damned"
        / "Ashes of Middenheim.pdf"
    )

    candidates = discover_pdfs(root)

    assert [candidate.source_path for candidate in candidates] == [earlier, later]
    assert [candidate.relative_path_posix for candidate in candidates] == [
        "Adventure Modules and Campaigns/Paths of the Damned/Ashes of Middenheim.pdf",
        "World Guides/Sigmar's Heirs.pdf",
    ]
    assert candidates[0].book_id == (
        "adventure-modules-and-campaigns-paths-of-the-damned-ashes-of-middenheim"
    )
    assert candidates[0].title == "Ashes of Middenheim"
    assert candidates[0].category == "Adventure Modules and Campaigns"
    assert candidates[0].folder_relative_path == (
        Path("Adventure Modules and Campaigns") / "Paths of the Damned"
    )
    assert candidates[0].folder_id == folder_id_for(candidates[0].folder_relative_path)


def test_discover_pdfs_returns_empty_list_when_no_pdfs(tmp_path: Path) -> None:
    root = tmp_path / "WFRP 2e"
    touch(root / "Core" / "notes.txt").write_text("private notes", encoding="utf-8")

    assert discover_pdfs(root) == []

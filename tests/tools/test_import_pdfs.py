from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import fitz

from tools.import_pdfs import main


def create_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    try:
        document.new_page()
        document.save(path)
    finally:
        document.close()
    return path


def book_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("select count(*) from books").fetchone()[0]


def test_main_imports_pdfs_and_uses_data_dir_default_db(
    capsys,
    tmp_path: Path,
) -> None:
    root = tmp_path / "pdfs"
    data_dir = tmp_path / "private-data"
    create_pdf(root / "Core" / "Core Rulebook.pdf")

    exit_code = main(["--pdf-root", str(root), "--data-dir", str(data_dir)])

    output = capsys.readouterr().out
    db_path = data_dir / "wfrp_companion.sqlite"
    assert exit_code == 0
    assert db_path.exists()
    assert book_count(db_path) == 1
    assert f"PDF root: {root}" in output
    assert f"DB path: {db_path}" in output
    assert "Copied: 1" in output
    assert "Failed: 0" in output


def test_main_honors_explicit_db_path(tmp_path: Path) -> None:
    root = tmp_path / "pdfs"
    data_dir = tmp_path / "private-data"
    db_path = tmp_path / "custom" / "library.sqlite"
    create_pdf(root / "Core" / "Core Rulebook.pdf")

    exit_code = main(
        [
            "--pdf-root",
            str(root),
            "--data-dir",
            str(data_dir),
            "--db-path",
            str(db_path),
        ]
    )

    assert exit_code == 0
    assert db_path.exists()
    assert not (data_dir / "wfrp_companion.sqlite").exists()
    assert book_count(db_path) == 1


def test_main_missing_pdf_root_exits_before_initializing_db(
    capsys,
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing"
    db_path = tmp_path / "db" / "wfrp.sqlite"

    exit_code = main(["--pdf-root", str(missing_root), "--db-path", str(db_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert not db_path.exists()
    assert f"PDF root does not exist or is not a directory: {missing_root}" in (
        captured.err
    )


def test_main_returns_nonzero_when_candidate_fails(tmp_path: Path) -> None:
    root = tmp_path / "pdfs"
    root.mkdir()
    (root / "broken.pdf").write_bytes(b"not a pdf")

    exit_code = main(["--pdf-root", str(root), "--data-dir", str(tmp_path / "data")])

    assert exit_code == 1


def test_main_prints_failure_details(capsys, tmp_path: Path) -> None:
    root = tmp_path / "pdfs"
    root.mkdir()
    (root / "broken.pdf").write_bytes(b"not a pdf")

    main(["--pdf-root", str(root), "--data-dir", str(tmp_path / "data")])

    output = capsys.readouterr().out
    assert "Failures:" in output
    assert "- broken.pdf [broken]: Failed to open PDF" in output


def test_import_pdfs_script_runs_from_file_path(tmp_path: Path) -> None:
    root = tmp_path / "pdfs"
    data_dir = tmp_path / "private-data"
    create_pdf(root / "Core" / "Core Rulebook.pdf")
    script_path = Path(__file__).resolve().parents[2] / "tools" / "import_pdfs.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--pdf-root",
            str(root),
            "--data-dir",
            str(data_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Copied: 1" in completed.stdout

from __future__ import annotations

import os
from pathlib import Path

import pytest

from wfrp_companion.library.storage import (
    copy_pdf_atomic,
    managed_file_matches,
    managed_pdf_path,
    sha256_file,
)


def test_sha256_file_hashes_file_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"the quick brown fox")

    assert sha256_file(source) == (
        "9ecb36561341d18eb65484e833efea61edc74b84cf5e6ae1b81c63533e25fc8f"
    )


def test_managed_pdf_path_is_absolute_and_versioned(tmp_path: Path) -> None:
    source_sha = "a" * 64

    path = managed_pdf_path(tmp_path / "data", "core-rules", source_sha)

    assert path.is_absolute()
    assert path == (
        tmp_path
        / "data"
        / "library"
        / "pdfs"
        / "core-rules"
        / f"source-{source_sha}.pdf"
    )


def test_copy_pdf_atomic_copies_bytes_and_returns_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nsynthetic")
    target = managed_pdf_path(tmp_path / "data", "core-rules", sha256_file(source))

    managed_sha = copy_pdf_atomic(source, target)

    assert managed_sha == sha256_file(source)
    assert target.read_bytes() == source.read_bytes()
    assert list(target.parent.glob("*.tmp-*")) == []


def test_copy_pdf_atomic_removes_temp_file_when_replace_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nsynthetic")
    target = managed_pdf_path(tmp_path / "data", "core-rules", sha256_file(source))

    def fail_replace(source_path: str | os.PathLike[str], target_path: str) -> None:
        raise OSError(f"cannot replace {source_path} -> {target_path}")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="cannot replace"):
        copy_pdf_atomic(source, target)

    assert not target.exists()
    assert list(target.parent.glob("*.tmp-*")) == []


def test_managed_file_matches_handles_missing_matching_and_mismatched_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"same bytes")
    expected_sha = sha256_file(source)

    assert managed_file_matches(tmp_path / "missing.pdf", expected_sha) is False
    assert managed_file_matches(source, expected_sha) is True
    assert managed_file_matches(source, "0" * 64) is False

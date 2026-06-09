from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import source_sets
from wfrp_companion.search import scope


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_book(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    title: str,
    category: str,
) -> None:
    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values ('core', null, 'Core', 'Core', 0)
        on conflict(id) do nothing
        """
    )
    connection.execute(
        """
        insert into books (
          id,
          folder_id,
          title,
          category,
          relative_path,
          original_source_path,
          managed_pdf_path,
          original_sha256,
          managed_sha256,
          page_count,
          copy_status,
          text_status,
          search_status,
          visual_status,
          discovered_at,
          updated_at
        )
        values (?, 'core', ?, ?, ?, ?, ?, ?, ?, 1, 'copied', 'imported',
                'indexed', 'not_scanned', '2026-06-04T00:00:00Z',
                '2026-06-04T00:00:00Z')
        """,
        (
            book_id,
            title,
            category,
            f"{category}/{title}.pdf",
            f"/source/{book_id}.pdf",
            f"/managed/{book_id}.pdf",
            f"sha-{book_id}",
            f"sha-{book_id}",
        ),
    )


def seed_books(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        insert_book(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
        )
        insert_book(
            connection,
            book_id="adventure-book",
            title="Adventure Book",
            category="Adventure Modules and Campaigns",
        )


def test_resolve_search_scope_supports_active_named_all_and_explicit_books(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)

    active = scope.resolve_search_scope(config)
    named = scope.resolve_search_scope(config, source_set_id="rules-core")
    all_books = scope.resolve_search_scope(config, all_books=True)
    explicit = scope.resolve_search_scope(
        config,
        book_ids=("missing-book",),
        validate_book_ids=False,
    )

    assert active == scope.SearchScope(
        label="active_source_set",
        source_set_id="rules-core",
        book_ids=("core-rules",),
        all_books=False,
    )
    assert named == scope.SearchScope(
        label="source_set",
        source_set_id="rules-core",
        book_ids=("core-rules",),
        all_books=False,
    )
    assert all_books == scope.SearchScope(
        label="all_books",
        source_set_id=None,
        book_ids=None,
        all_books=True,
    )
    assert explicit == scope.SearchScope(
        label="book_ids",
        source_set_id=None,
        book_ids=("missing-book",),
        all_books=False,
    )


def test_resolve_search_scope_rejects_conflicting_scope_inputs(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)

    with pytest.raises(scope.SearchScopeConflictError):
        scope.resolve_search_scope(
            config,
            all_books=True,
            source_set_id="rules-core",
        )
    with pytest.raises(scope.SearchScopeConflictError):
        scope.resolve_search_scope(
            config,
            all_books=True,
            book_ids=("core-rules",),
        )
    with pytest.raises(scope.SearchScopeConflictError):
        scope.resolve_search_scope(
            config,
            source_set_id="rules-core",
            book_ids=("core-rules",),
        )


def test_resolve_search_scope_requires_valid_active_and_named_source_sets(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)

    with pytest.raises(source_sets.ActiveSourceSetMissingError):
        scope.resolve_search_scope(config)

    source_sets.ensure_builtin_source_sets(config)
    with pytest.raises(source_sets.SourceSetNotFoundError):
        scope.resolve_search_scope(config, source_set_id="missing-set")


def test_resolve_search_scope_can_validate_explicit_book_ids(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)

    valid = scope.resolve_search_scope(
        config,
        book_ids=("core-rules",),
        validate_book_ids=True,
    )
    empty = scope.resolve_search_scope(config, book_ids=(), validate_book_ids=True)

    with pytest.raises(scope.SearchBookNotFoundError, match="missing-book"):
        scope.resolve_search_scope(
            config,
            book_ids=("core-rules", "missing-book"),
            validate_book_ids=True,
        )

    assert valid.book_ids == ("core-rules",)
    assert empty.book_ids == ()

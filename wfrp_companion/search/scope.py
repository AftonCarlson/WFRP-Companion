from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import source_sets


@dataclass(frozen=True)
class SearchScope:
    label: str
    source_set_id: str | None
    book_ids: tuple[str, ...] | None
    all_books: bool


class SearchScopeError(Exception):
    pass


class SearchScopeConflictError(SearchScopeError):
    pass


class SearchBookNotFoundError(SearchScopeError):
    pass


def resolve_search_scope(
    config: AppConfig,
    *,
    all_books: bool = False,
    source_set_id: str | None = None,
    book_ids: Sequence[str] | None = None,
    validate_book_ids: bool = False,
) -> SearchScope:
    explicit_book_ids = None if book_ids is None else tuple(book_ids)
    requested_scopes = sum(
        [
            1 if all_books else 0,
            1 if source_set_id is not None else 0,
            1 if explicit_book_ids is not None else 0,
        ]
    )
    if requested_scopes > 1:
        raise SearchScopeConflictError(
            "Search scope must use only one of all_books, source_set_id, or book_ids."
        )

    if all_books:
        return SearchScope(
            label="all_books",
            source_set_id=None,
            book_ids=None,
            all_books=True,
        )

    if source_set_id is not None:
        return SearchScope(
            label="source_set",
            source_set_id=source_set_id,
            book_ids=source_sets.enabled_book_ids(config, source_set_id),
            all_books=False,
        )

    if explicit_book_ids is not None:
        if validate_book_ids:
            require_existing_book_ids(config, explicit_book_ids)
        return SearchScope(
            label="book_ids",
            source_set_id=None,
            book_ids=explicit_book_ids,
            all_books=False,
        )

    active_source_set_id = source_sets.get_active_source_set_id(config)
    if active_source_set_id is None:
        raise source_sets.ActiveSourceSetMissingError(
            "No active source set. Run tools/source_sets.py init or use --all-books."
        )
    return SearchScope(
        label="active_source_set",
        source_set_id=active_source_set_id,
        book_ids=source_sets.enabled_book_ids(config, active_source_set_id),
        all_books=False,
    )


def require_existing_book_ids(config: AppConfig, book_ids: tuple[str, ...]) -> None:
    if not book_ids:
        return

    placeholders = ",".join("?" for _ in book_ids)
    with initialize_database(config.db_path) as connection:
        rows = connection.execute(
            f"""
            select id
            from books
            where id in ({placeholders})
            """,
            book_ids,
        ).fetchall()
    found = {row["id"] for row in rows}
    missing = tuple(book_id for book_id in book_ids if book_id not in found)
    if missing:
        raise SearchBookNotFoundError(f"Book not found: {missing[0]}")

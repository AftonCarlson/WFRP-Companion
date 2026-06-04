from __future__ import annotations

from fastapi import APIRouter

from wfrp_companion.api import errors
from wfrp_companion.api.dependencies import ConfigDependency
from wfrp_companion.api.schemas import (
    ActiveSourceSetResponse,
    SetActiveSourceSetRequest,
    SetSourceSetBookRequest,
    SourceSetBookResponse,
    SourceSetBooksResponse,
    SourceSetResponse,
    SourceSetsResponse,
)
from wfrp_companion.library import source_sets


router = APIRouter(tags=["source-sets"])


@router.get("/source-sets", response_model=SourceSetsResponse)
def list_source_sets(config: ConfigDependency) -> SourceSetsResponse:
    active_source_set_id = source_sets.get_active_source_set_id(config)
    rows = [
        SourceSetResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            is_builtin=row.is_builtin,
            active=row.id == active_source_set_id,
        )
        for row in source_sets.list_source_sets(config)
    ]
    return SourceSetsResponse(
        active_source_set_id=active_source_set_id,
        source_sets=rows,
    )


@router.get("/source-sets/active", response_model=ActiveSourceSetResponse)
def get_active_source_set(config: ConfigDependency) -> ActiveSourceSetResponse:
    active_source_set_id = source_sets.get_active_source_set_id(config)
    if active_source_set_id is None:
        error = source_sets.ActiveSourceSetMissingError(
            "Active source set is missing or invalid."
        )
        raise errors.source_set_error(error)
    return ActiveSourceSetResponse(source_set_id=active_source_set_id)


@router.put("/source-sets/active", response_model=ActiveSourceSetResponse)
def set_active_source_set(
    request: SetActiveSourceSetRequest,
    config: ConfigDependency,
) -> ActiveSourceSetResponse:
    try:
        source_sets.set_active_source_set(config, request.source_set_id)
    except source_sets.SourceSetError as error:
        raise errors.source_set_error(error) from error
    return ActiveSourceSetResponse(source_set_id=request.source_set_id)


@router.get(
    "/source-sets/{source_set_id}/books",
    response_model=SourceSetBooksResponse,
)
def list_source_set_books(
    source_set_id: str,
    config: ConfigDependency,
) -> SourceSetBooksResponse:
    try:
        books = source_sets.list_source_set_books(config, source_set_id)
    except source_sets.SourceSetError as error:
        raise errors.source_set_error(error) from error
    return SourceSetBooksResponse(
        source_set_id=source_set_id,
        books=[source_set_book_response(book) for book in books],
    )


@router.put(
    "/source-sets/{source_set_id}/books/{book_id}",
    response_model=SourceSetBookResponse,
)
def set_source_set_book(
    source_set_id: str,
    book_id: str,
    request: SetSourceSetBookRequest,
    config: ConfigDependency,
) -> SourceSetBookResponse:
    try:
        source_sets.set_book_enabled(
            config,
            source_set_id,
            book_id,
            request.enabled,
        )
        books = source_sets.list_source_set_books(config, source_set_id)
    except source_sets.SourceSetError as error:
        raise errors.source_set_error(error) from error
    return next(
        source_set_book_response(book) for book in books if book.book_id == book_id
    )


def source_set_book_response(
    book: source_sets.SourceSetBook,
) -> SourceSetBookResponse:
    return SourceSetBookResponse(
        source_set_id=book.source_set_id,
        book_id=book.book_id,
        title=book.title,
        category=book.category,
        enabled=book.enabled,
        search_ready=book.search_ready,
    )

from __future__ import annotations

from fastapi import HTTPException

from wfrp_companion.assistant import chat_store
from wfrp_companion.library import catalog
from wfrp_companion.library import source_sets
from wfrp_companion.search import scope


def http_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def catalog_error(error: catalog.CatalogError) -> HTTPException:
    if isinstance(error, catalog.BookNotFoundError | catalog.PageNotFoundError):
        return http_error(404, str(error))
    if isinstance(
        error,
        catalog.ReaderUnavailableError
        | catalog.PageTextUnavailableError
        | catalog.ManagedPdfMissingError
        | catalog.ManagedPdfPathRejectedError,
    ):
        return http_error(409, str(error))
    return http_error(500, "Unexpected catalog error")


def source_set_error(error: source_sets.SourceSetError) -> HTTPException:
    if isinstance(
        error,
        source_sets.SourceSetNotFoundError | source_sets.BookNotFoundError,
    ):
        return http_error(404, str(error))
    if isinstance(error, source_sets.ActiveSourceSetMissingError):
        return http_error(409, str(error))
    if isinstance(error, source_sets.SourceSetConflictError):
        return http_error(409, str(error))
    return http_error(500, "Unexpected source set error")


def search_scope_error(error: scope.SearchScopeError) -> HTTPException:
    if isinstance(error, scope.SearchScopeConflictError):
        return http_error(422, str(error))
    if isinstance(error, scope.SearchBookNotFoundError):
        return http_error(404, str(error))
    return http_error(500, "Unexpected search scope error")


def chat_store_error(error: chat_store.ChatStoreError) -> HTTPException:
    if isinstance(
        error,
        chat_store.ChatThreadNotFoundError | chat_store.ModelRunNotFoundError,
    ):
        return http_error(404, str(error))
    if isinstance(error, chat_store.ModelRunNotRetryableError):
        return http_error(409, str(error))
    return http_error(500, "Unexpected chat store error")

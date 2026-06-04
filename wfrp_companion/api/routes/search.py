from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from wfrp_companion.api import errors
from wfrp_companion.api.dependencies import ConfigDependency
from wfrp_companion.api.schemas import (
    ExactSearchResponse,
    SearchHitResponse,
    SearchScopeResponse,
)
from wfrp_companion.library import source_sets
from wfrp_companion.search import scope
from wfrp_companion.search.fts import search_exact as search_exact_fts


router = APIRouter(tags=["search"])


@router.get("/search/exact", response_model=ExactSearchResponse)
def search_exact(
    config: ConfigDependency,
    query: Annotated[str, Query(min_length=1)],
    book_id: Annotated[list[str] | None, Query()] = None,
    source_set_id: str | None = None,
    all_books: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ExactSearchResponse:
    try:
        search_scope = scope.resolve_search_scope(
            config,
            all_books=all_books,
            source_set_id=source_set_id,
            book_ids=book_id,
            validate_book_ids=True,
        )
    except scope.SearchScopeError as error:
        raise errors.search_scope_error(error) from error
    except source_sets.SourceSetError as error:
        raise errors.source_set_error(error) from error

    hits = search_exact_fts(
        config,
        query,
        book_ids=search_scope.book_ids,
        limit=limit,
    )
    return ExactSearchResponse(
        query=query,
        scope=SearchScopeResponse(
            label=search_scope.label,
            source_set_id=search_scope.source_set_id,
            book_ids=list(search_scope.book_ids)
            if search_scope.book_ids is not None
            else None,
            all_books=search_scope.all_books,
        ),
        hits=[SearchHitResponse(**hit.__dict__) for hit in hits],
    )

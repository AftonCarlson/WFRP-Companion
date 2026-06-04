from __future__ import annotations

from wfrp_companion.api import errors
from wfrp_companion.library import catalog
from wfrp_companion.library import source_sets
from wfrp_companion.search import scope


def test_catalog_error_defensive_fallback() -> None:
    response = errors.catalog_error(catalog.CatalogError("unexpected"))

    assert response.status_code == 500
    assert response.detail == "Unexpected catalog error"


def test_source_set_error_maps_conflict_and_defensive_fallback() -> None:
    conflict = errors.source_set_error(source_sets.SourceSetConflictError("conflict"))
    fallback = errors.source_set_error(source_sets.SourceSetError("unexpected"))

    assert conflict.status_code == 409
    assert conflict.detail == "conflict"
    assert fallback.status_code == 500
    assert fallback.detail == "Unexpected source set error"


def test_search_scope_error_defensive_fallback() -> None:
    response = errors.search_scope_error(scope.SearchScopeError("unexpected"))

    assert response.status_code == 500
    assert response.detail == "Unexpected search scope error"

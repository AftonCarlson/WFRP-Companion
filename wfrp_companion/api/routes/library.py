from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import FileResponse

from wfrp_companion.api import errors
from wfrp_companion.api.dependencies import ConfigDependency
from wfrp_companion.api.schemas import (
    BookDetailResponse,
    BooksResponse,
    BookSummaryResponse,
    PageReferenceResponse,
)
from wfrp_companion.library import catalog


router = APIRouter(tags=["library"])


@router.get("/books", response_model=BooksResponse)
def list_books(config: ConfigDependency) -> BooksResponse:
    books = [
        BookSummaryResponse(**book.__dict__)
        for book in catalog.list_books(config)
    ]
    return BooksResponse(books=books)


@router.get("/books/{book_id}/pages/{page_number}", response_model=PageReferenceResponse)
def get_page(
    book_id: str,
    page_number: int,
    config: ConfigDependency,
) -> PageReferenceResponse:
    try:
        page = catalog.get_page(config, book_id, page_number)
    except catalog.CatalogError as error:
        raise errors.catalog_error(error) from error
    return PageReferenceResponse(**page.__dict__)


@router.get("/books/{book_id}/pdf")
def get_book_pdf(book_id: str, config: ConfigDependency) -> FileResponse:
    try:
        book = catalog.get_book(config, book_id)
        path = catalog.reader_pdf_path(config, book_id)
    except catalog.CatalogError as error:
        raise errors.catalog_error(error) from error
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{book.title}.pdf",
        content_disposition_type="inline",
    )


@router.get("/books/{book_id}", response_model=BookDetailResponse)
def get_book(book_id: str, config: ConfigDependency) -> BookDetailResponse:
    try:
        book = catalog.get_book(config, book_id)
    except catalog.CatalogError as error:
        raise errors.catalog_error(error) from error
    return BookDetailResponse(**book.__dict__)

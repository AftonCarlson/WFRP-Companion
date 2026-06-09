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
    PageTextResponse,
    RetrievalStatusResponse,
)
from wfrp_companion.library import catalog
from wfrp_companion.library import retrieval_status


router = APIRouter(tags=["library"])


@router.get("/books", response_model=BooksResponse)
def list_books(config: ConfigDependency) -> BooksResponse:
    books = [
        book_summary_response(book)
        for book in catalog.list_books(config)
    ]
    return BooksResponse(books=books)


@router.get("/retrieval/status", response_model=RetrievalStatusResponse)
def get_retrieval_status(config: ConfigDependency) -> RetrievalStatusResponse:
    status = retrieval_status.get_retrieval_status(config)
    return RetrievalStatusResponse(**status.__dict__)


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


@router.get(
    "/books/{book_id}/pages/{page_number}/text",
    response_model=PageTextResponse,
)
def get_page_text(
    book_id: str,
    page_number: int,
    config: ConfigDependency,
) -> PageTextResponse:
    try:
        page = catalog.get_page_text(config, book_id, page_number)
    except catalog.CatalogError as error:
        raise errors.catalog_error(error) from error
    return PageTextResponse(**page.__dict__)


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
    return book_detail_response(book)


def book_summary_response(book: catalog.BookSummary) -> BookSummaryResponse:
    return BookSummaryResponse(
        id=book.id,
        title=book.title,
        category=book.category,
        relative_path=book.relative_path,
        page_count=book.page_count,
        copy_status=book.copy_status,
        text_status=book.text_status,
        search_status=book.search_status,
        visual_status=book.visual_status,
        reader_ready=book.reader_ready,
        search_ready=book.search_ready,
        fully_ready=book.fully_ready,
        needs_attention=book.needs_attention,
        vector_status=book.vector_status,
        embedding_provider=book.embedding_provider,
        embedding_dimensions=book.embedding_dimensions,
    )


def book_detail_response(book: catalog.BookDetail) -> BookDetailResponse:
    return BookDetailResponse(
        **book_summary_response(book).model_dump(),
        managed_pdf_available=book.managed_pdf_available,
    )

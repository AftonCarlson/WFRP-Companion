from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str


class BookSummaryResponse(BaseModel):
    id: str
    title: str
    category: str
    relative_path: str
    page_count: int
    copy_status: str
    text_status: str
    search_status: str
    visual_status: str
    reader_ready: bool
    search_ready: bool
    fully_ready: bool
    needs_attention: bool


class BookDetailResponse(BookSummaryResponse):
    managed_pdf_available: bool


class BooksResponse(BaseModel):
    books: list[BookSummaryResponse]


class PageReferenceResponse(BaseModel):
    page_id: str
    book_id: str
    page_number: int
    page_label: str | None
    has_text: bool
    text_chars: int
    image_count: int


class SourceSetResponse(BaseModel):
    id: str
    name: str
    description: str | None
    is_builtin: bool
    active: bool


class SourceSetsResponse(BaseModel):
    active_source_set_id: str | None
    source_sets: list[SourceSetResponse]


class ActiveSourceSetResponse(BaseModel):
    source_set_id: str


class SetActiveSourceSetRequest(BaseModel):
    source_set_id: str


class SourceSetBookResponse(BaseModel):
    source_set_id: str
    book_id: str
    title: str
    category: str
    enabled: bool
    search_ready: bool


class SourceSetBooksResponse(BaseModel):
    source_set_id: str
    books: list[SourceSetBookResponse]


class SetSourceSetBookRequest(BaseModel):
    enabled: bool


class SearchScopeResponse(BaseModel):
    label: str
    source_set_id: str | None
    book_ids: list[str] | None
    all_books: bool


class SearchHitResponse(BaseModel):
    rank: int
    book_id: str
    title: str
    category: str
    page_id: str
    page_number: int
    snippet: str
    score: float


class ExactSearchResponse(BaseModel):
    query: str
    scope: SearchScopeResponse
    hits: list[SearchHitResponse]

from __future__ import annotations

from pydantic import BaseModel, Field


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
    vector_status: str
    embedding_provider: str | None
    embedding_dimensions: int | None


class BookDetailResponse(BookSummaryResponse):
    managed_pdf_available: bool


class BooksResponse(BaseModel):
    books: list[BookSummaryResponse]


class RetrievalStatusResponse(BaseModel):
    books_total: int
    books_enabled: int
    page_text_indexed: int
    source_objects_indexed: int
    table_or_stat_indexed: int
    vectorized_current: int
    vectorized_enabled: int
    embedding_provider: str
    embedding_dimensions: int | None
    vector_status: str


class PageReferenceResponse(BaseModel):
    page_id: str
    book_id: str
    page_number: int
    page_label: str | None
    has_text: bool
    text_chars: int
    image_count: int


class PageTextResponse(BaseModel):
    page_id: str
    book_id: str
    page_number: int
    page_label: str | None
    text: str
    text_chars: int


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
    pdf_page_number: int
    page_label: str | None
    snippet: str
    score: float


class ExactSearchResponse(BaseModel):
    query: str
    scope: SearchScopeResponse
    hits: list[SearchHitResponse]


class CreateChatThreadRequest(BaseModel):
    title: str | None = None
    source_set_id: str | None = None


class ChatThreadResponse(BaseModel):
    id: str
    title: str | None
    active_source_set_id: str | None
    source_book_count: int
    created_at: str
    updated_at: str


class ChatThreadsResponse(BaseModel):
    threads: list[ChatThreadResponse]


class ChatMessageResponse(BaseModel):
    id: str
    thread_id: str
    role: str
    content: str
    created_at: str


class ChatCitationResponse(BaseModel):
    book_id: str
    title: str
    category: str
    page_id: str
    page_number: int
    pdf_page_number: int
    page_label: str | None
    snippet: str
    rank: int
    score: float
    page_range_label: str | None = None


class ChatResearchEventResponse(BaseModel):
    type: str
    label: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ReaderContextRequest(BaseModel):
    active_book_id: str | None = None
    active_pdf_page_number: int | None = Field(default=None, ge=1)
    active_printed_page_label: str | None = None
    open_book_ids: list[str] = Field(default_factory=list)


class SendChatMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    idempotency_key: str | None = None
    reader_context: ReaderContextRequest | None = None


class RetryModelRunRequest(BaseModel):
    idempotency_key: str | None = None


class ModelRunResponse(BaseModel):
    id: str
    thread_id: str
    user_message_id: str | None
    assistant_message_id: str | None
    retrieval_run_id: str | None
    retry_of_model_run_id: str | None
    status: str
    provider: str
    model: str
    provider_response_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    retryable: bool


class SendChatMessageResponse(BaseModel):
    thread: ChatThreadResponse
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse | None
    model_run: ModelRunResponse
    citations: list[ChatCitationResponse]


class ChatTurnResponse(BaseModel):
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse | None
    model_run: ModelRunResponse
    citations: list[ChatCitationResponse]
    research_events: list[ChatResearchEventResponse] = Field(default_factory=list)


class ChatThreadDetailResponse(BaseModel):
    thread: ChatThreadResponse
    source_book_ids: list[str]
    turns: list[ChatTurnResponse]

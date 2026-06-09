export type HealthResponse = {
  status: string;
  database: string;
};

export type BookSummaryResponse = {
  id: string;
  title: string;
  category: string;
  relative_path: string;
  page_count: number;
  copy_status: string;
  text_status: string;
  search_status: string;
  visual_status: string;
  reader_ready: boolean;
  search_ready: boolean;
  fully_ready: boolean;
  needs_attention: boolean;
  vector_status: string;
  embedding_provider: string | null;
  embedding_dimensions: number | null;
};

export type BooksResponse = {
  books: BookSummaryResponse[];
};

export type RetrievalStatusResponse = {
  books_total: number;
  books_enabled: number;
  page_text_indexed: number;
  source_objects_indexed: number;
  table_or_stat_indexed: number;
  vectorized_current: number;
  vectorized_enabled: number;
  embedding_provider: string;
  embedding_dimensions: number | null;
  vector_status: string;
};

export type SourceSetResponse = {
  id: string;
  name: string;
  description: string | null;
  is_builtin: boolean;
  active: boolean;
};

export type SourceSetsResponse = {
  active_source_set_id: string | null;
  source_sets: SourceSetResponse[];
};

export type SourceSetBookResponse = {
  source_set_id: string;
  book_id: string;
  title: string;
  category: string;
  enabled: boolean;
  search_ready: boolean;
};

export type SourceSetBooksResponse = {
  source_set_id: string;
  books: SourceSetBookResponse[];
};

export type SearchScopeResponse = {
  label: string;
  source_set_id: string | null;
  book_ids: string[] | null;
  all_books: boolean;
};

export type SearchHitResponse = {
  rank: number;
  book_id: string;
  title: string;
  category: string;
  page_id: string;
  page_number: number;
  pdf_page_number: number;
  page_label: string | null;
  snippet: string;
  score: number;
};

export type ExactSearchResponse = {
  query: string;
  scope: SearchScopeResponse;
  hits: SearchHitResponse[];
};

export type PageTextResponse = {
  page_id: string;
  book_id: string;
  page_number: number;
  page_label: string | null;
  text: string;
  text_chars: number;
};

export type ChatThreadResponse = {
  id: string;
  title: string | null;
  active_source_set_id: string | null;
  source_book_count: number;
  created_at: string;
  updated_at: string;
};

export type ChatThreadsResponse = {
  threads: ChatThreadResponse[];
};

export type ChatMessageResponse = {
  id: string;
  thread_id: string;
  role: string;
  content: string;
  created_at: string;
};

export type ModelRunResponse = {
  id: string;
  thread_id: string;
  user_message_id: string | null;
  assistant_message_id: string | null;
  retrieval_run_id: string | null;
  retry_of_model_run_id: string | null;
  status: string;
  provider: string;
  model: string;
  provider_response_id: string | null;
  error_code: string | null;
  error_message: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  retryable: boolean;
};

export type ChatCitationResponse = {
  book_id: string;
  title: string;
  category: string;
  page_id: string;
  page_number: number;
  pdf_page_number: number;
  page_label: string | null;
  snippet: string;
  rank: number;
  score: number;
  page_range_label?: string | null;
};

export type ChatResearchEventResponse = {
  type: string;
  label: string;
  metadata?: Record<string, unknown>;
};

export type ReaderContextRequest = {
  active_book_id?: string | null;
  active_pdf_page_number?: number | null;
  active_printed_page_label?: string | null;
  open_book_ids?: string[];
};

export type SendChatMessageResponse = {
  thread: ChatThreadResponse;
  user_message: ChatMessageResponse;
  assistant_message: ChatMessageResponse | null;
  model_run: ModelRunResponse;
  citations: ChatCitationResponse[];
};

export type ChatTurnResponse = {
  user_message: ChatMessageResponse;
  assistant_message: ChatMessageResponse | null;
  model_run: ModelRunResponse;
  citations: ChatCitationResponse[];
  research_events?: ChatResearchEventResponse[];
};

export type ChatThreadDetailResponse = {
  thread: ChatThreadResponse;
  source_book_ids: string[];
  turns: ChatTurnResponse[];
};

export type ChatStreamEvent = {
  type:
    | "accepted"
    | "research_started"
    | "research_plan"
    | "tool_call"
    | "retrieval"
    | "tool_result"
    | "evidence_validation"
    | "finalizing"
    | "delta"
    | "completed"
    | "failed";
  thread?: ChatThreadResponse | null;
  user_message?: ChatMessageResponse | null;
  assistant_message?: ChatMessageResponse | null;
  model_run?: ModelRunResponse | null;
  citations?: ChatCitationResponse[];
  text_delta?: string | null;
  error_message?: string | null;
  metadata?: Record<string, unknown> | null;
};

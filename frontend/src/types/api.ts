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
};

export type BooksResponse = {
  books: BookSummaryResponse[];
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

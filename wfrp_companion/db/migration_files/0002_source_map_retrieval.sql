create table if not exists book_retrieval_status (
  book_id text primary key references books(id) on delete cascade,
  source_map_status text not null default 'not_started',
  table_index_status text not null default 'not_started',
  vector_status text not null default 'disabled',
  page_label_status text not null default 'not_started',
  page_text_snapshot_sha256 text,
  source_object_snapshot_sha256 text,
  source_map_snapshot_sha256 text,
  vector_snapshot_sha256 text,
  source_map_started_at text,
  vector_started_at text,
  table_index_started_at text,
  page_label_started_at text,
  embedding_model text,
  embedding_dimensions integer,
  last_error text,
  updated_at text not null,
  check(source_map_status in ('not_started', 'indexing', 'indexed', 'needs_refresh', 'failed')),
  check(table_index_status in ('not_started', 'indexing', 'indexed', 'needs_refresh', 'failed', 'disabled')),
  check(vector_status in ('not_started', 'indexing', 'indexed', 'needs_refresh', 'failed', 'disabled')),
  check(page_label_status in ('not_started', 'calibrating', 'calibrated', 'needs_review', 'failed')),
  check(embedding_dimensions is null or embedding_dimensions > 0)
);

create table if not exists book_source_maps (
  book_id text primary key references books(id) on delete cascade,
  summary text not null,
  aliases_json text not null default '[]',
  chapters_json text not null default '[]',
  best_source_for_json text not null default '[]',
  index_terms_json text not null default '[]',
  glossary_terms_json text not null default '[]',
  source_object_snapshot_sha256 text not null,
  schema_version integer not null default 1,
  builder_version text not null,
  created_at text not null,
  updated_at text not null,
  check(schema_version >= 1)
);

create table if not exists retrieval_run_source_books (
  retrieval_run_id text not null references retrieval_runs(id) on delete cascade,
  source_set_id text references source_sets(id) on delete set null,
  book_id text not null references books(id) on delete cascade,
  book_title_snapshot text not null,
  captured_at text not null,
  primary key(retrieval_run_id, book_id)
);

create index if not exists ix_retrieval_run_source_books_book
on retrieval_run_source_books(book_id, captured_at);

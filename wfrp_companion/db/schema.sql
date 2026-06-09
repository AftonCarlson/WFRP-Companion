create table if not exists app_settings (
  key text primary key,
  value_json text not null,
  updated_at text not null
);

create table if not exists schema_migrations (
  id text primary key,
  applied_at text not null
);

create table if not exists library_folders (
  id text primary key,
  parent_id text references library_folders(id),
  name text not null,
  relative_path text not null unique,
  sort_order integer not null default 0
);

create table if not exists books (
  id text primary key,
  folder_id text not null references library_folders(id),
  title text not null,
  category text not null,
  relative_path text not null unique,
  original_source_path text not null,
  managed_pdf_path text not null,
  original_sha256 text not null,
  managed_sha256 text,
  page_count integer not null,
  copy_status text not null,
  text_status text not null,
  search_status text not null,
  visual_status text not null,
  enabled_default integer not null default 0,
  metadata_json text not null default '{}',
  discovered_at text not null,
  copied_at text,
  updated_at text not null,
  check(copy_status in ('discovered', 'copying', 'copied', 'managed_missing', 'failed')),
  check(copy_status != 'copied' or managed_sha256 is not null),
  check(text_status in ('not_imported', 'importing', 'imported', 'needs_refresh', 'failed')),
  check(search_status in ('not_indexed', 'indexing', 'indexed', 'needs_refresh', 'failed')),
  check(visual_status in ('not_scanned', 'scanning', 'scanned', 'needs_refresh', 'failed')),
  check(enabled_default in (0, 1))
);

create table if not exists pages (
  id text primary key,
  book_id text not null references books(id) on delete cascade,
  page_number integer not null,
  page_label text,
  extraction_method text not null,
  embedded_text_chars integer not null,
  text_chars integer not null,
  word_count integer not null,
  image_count integer not null,
  ocr_attempted integer not null,
  ocr_error text,
  has_text integer not null,
  metadata_json text not null default '{}',
  unique(book_id, page_number),
  unique(id, book_id, page_number)
);

create table if not exists page_text (
  page_id text primary key references pages(id) on delete cascade,
  text text not null,
  text_sha256 text not null,
  generated_at text not null
);

create table if not exists page_search (
  rowid integer primary key,
  page_id text not null unique references pages(id) on delete cascade,
  book_id text not null references books(id) on delete cascade,
  folder_id text not null references library_folders(id),
  category text not null,
  title text not null,
  page_number integer not null,
  text text not null
);

create virtual table if not exists page_search_fts using fts5(
  title,
  text,
  content='page_search',
  content_rowid='rowid'
);

create table if not exists source_sets (
  id text primary key,
  name text not null unique,
  description text,
  is_builtin integer not null default 0,
  created_at text not null,
  updated_at text not null,
  check(is_builtin in (0, 1))
);

create table if not exists source_set_books (
  source_set_id text not null references source_sets(id) on delete cascade,
  book_id text not null references books(id) on delete cascade,
  enabled integer not null,
  updated_at text not null,
  check(enabled in (0, 1)),
  primary key(source_set_id, book_id)
);

create table if not exists page_assets (
  id text primary key,
  page_id text not null references pages(id) on delete cascade,
  book_id text not null references books(id) on delete cascade,
  page_number integer not null,
  kind text not null,
  file_path text,
  media_type text,
  width integer,
  height integer,
  dpi integer,
  bbox_json text,
  source_xref integer,
  sha256 text,
  perceptual_hash text,
  byte_size integer,
  confidence real not null default 0,
  review_status text not null default 'unreviewed',
  extracted_at text,
  metadata_json text not null default '{}',
  foreign key (page_id, book_id, page_number)
    references pages(id, book_id, page_number) on delete cascade,
  check(kind in ('embedded_image', 'page_render', 'thumbnail', 'visual_candidate')),
  check(review_status in ('unreviewed', 'auto_labeled', 'reviewed', 'rejected'))
);

create table if not exists asset_labels (
  id text primary key,
  asset_id text not null references page_assets(id) on delete cascade,
  label text not null,
  source text not null,
  confidence real not null,
  is_current integer not null default 0,
  created_at text not null,
  check(label in ('cover', 'map_candidate', 'illustration_candidate', 'handout_candidate', 'table_candidate', 'character_sheet', 'icon_fragment', 'unknown', 'rejected')),
  check(source in ('heuristic', 'user')),
  check(is_current in (0, 1))
);

create unique index if not exists ux_page_assets_page_kind_hash
on page_assets(page_id, kind, sha256)
where sha256 is not null;

create unique index if not exists ux_page_assets_page_kind_phash
on page_assets(page_id, kind, perceptual_hash)
where sha256 is null and perceptual_hash is not null;

create unique index if not exists ux_asset_labels_current
on asset_labels(asset_id)
where is_current = 1;

create table if not exists source_objects (
  id text primary key,
  book_id text not null references books(id) on delete cascade,
  page_id text not null references pages(id) on delete cascade,
  object_type text not null,
  parent_object_id text references source_objects(id) on delete cascade,
  title text,
  heading_path_json text not null default '[]',
  page_start integer not null,
  page_end integer not null,
  char_start integer,
  char_end integer,
  bbox_json text,
  text text not null,
  search_text text not null,
  metadata_json text not null default '{}',
  confidence real not null default 0,
  extraction_method text not null,
  text_snapshot_sha256 text not null,
  created_at text not null,
  updated_at text not null,
  foreign key (page_id, book_id, page_start)
    references pages(id, book_id, page_number) on delete cascade,
  check(object_type in (
    'rule_section',
    'table',
    'table_row',
    'stat_block',
    'npc_profile',
    'monster_profile',
    'location_description',
    'encounter',
    'boxed_text',
    'map_reference',
    'image_reference',
    'index_entry',
    'glossary_entry',
    'cross_reference',
    'page_chunk'
  )),
  check(confidence >= 0 and confidence <= 1),
  check(page_start >= 1),
  check(page_end >= page_start)
);

create table if not exists source_object_links (
  id text primary key,
  from_object_id text not null references source_objects(id) on delete cascade,
  to_object_id text references source_objects(id) on delete cascade,
  to_book_id text references books(id) on delete set null,
  to_page_id text references pages(id) on delete set null,
  link_type text not null,
  label text,
  confidence real not null default 0,
  evidence_json text not null default '{}',
  created_at text not null,
  check(link_type in (
    'index_entry',
    'cross_reference',
    'same_section',
    'table_row',
    'stat_profile',
    'glossary_definition',
    'map_reference',
    'image_reference',
    'entity_mention'
  )),
  check(confidence >= 0 and confidence <= 1)
);

create table if not exists book_object_status (
  book_id text primary key references books(id) on delete cascade,
  status text not null,
  object_count integer not null default 0,
  table_count integer not null default 0,
  stat_block_count integer not null default 0,
  location_count integer not null default 0,
  text_snapshot_sha256 text,
  extractor_version text,
  last_error text,
  updated_at text not null,
  check(status in ('not_started', 'extracting', 'extracted', 'indexing', 'indexed', 'failed')),
  check(object_count >= 0),
  check(table_count >= 0),
  check(stat_block_count >= 0),
  check(location_count >= 0)
);

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
  embedding_provider text,
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

create table if not exists book_page_label_calibrations (
  book_id text primary key references books(id) on delete cascade,
  status text not null,
  method text not null,
  calibration_json text not null default '{}',
  page_text_snapshot_sha256 text not null,
  last_error text,
  reviewed_at text,
  updated_at text not null,
  check(status in ('not_started', 'calibrating', 'calibrated', 'needs_review', 'failed')),
  check(length(method) > 0)
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

create table if not exists book_query_profiles (
  book_id text not null references books(id) on delete cascade,
  query_type text not null,
  confidence real not null,
  evidence_json text not null default '{}',
  updated_at text not null,
  primary key(book_id, query_type),
  check(query_type in (
    'rules_lookup',
    'table_lookup',
    'stat_block_lookup',
    'npc_lookup',
    'monster_lookup',
    'location_lookup',
    'adventure_scene_lookup',
    'lore_lookup',
    'source_navigation'
  )),
  check(confidence >= 0 and confidence <= 1)
);

create table if not exists source_object_search (
  rowid integer primary key,
  source_object_id text not null unique references source_objects(id) on delete cascade,
  book_id text not null references books(id) on delete cascade,
  page_id text not null references pages(id) on delete cascade,
  object_type text not null,
  title text,
  heading_path text not null,
  page_start integer not null,
  page_end integer not null,
  confidence real not null,
  search_text text not null
);

create virtual table if not exists source_object_search_fts using fts5(
  title,
  heading_path,
  object_type,
  search_text,
  content='source_object_search',
  content_rowid='rowid'
);

create table if not exists source_object_embeddings (
  id text primary key,
  source_object_id text not null references source_objects(id) on delete cascade,
  book_id text not null references books(id) on delete cascade,
  embedding_provider text not null default 'local-hash',
  embedding_model text not null,
  embedding_dimensions integer not null,
  text_snapshot_sha256 text not null,
  vector_blob blob not null,
  created_at text not null,
  updated_at text not null,
  check(embedding_dimensions > 0)
);

create unique index if not exists ux_source_object_embeddings_current
on source_object_embeddings(
  source_object_id,
  embedding_provider,
  embedding_model,
  embedding_dimensions,
  text_snapshot_sha256
);

create index if not exists ix_source_object_embeddings_book_model
on source_object_embeddings(
  book_id,
  embedding_provider,
  embedding_model,
  embedding_dimensions
);

create table if not exists ingest_jobs (
  id text primary key,
  job_type text not null,
  target_id text,
  status text not null,
  idempotency_key text not null unique,
  attempts integer not null default 0,
  last_error text,
  created_at text not null,
  updated_at text not null,
  completed_at text,
  check(job_type in ('copy_pdf', 'import_page_text', 'rebuild_fts', 'scan_visual_assets', 'render_page', 'extract_source_objects', 'rebuild_source_object_fts', 'rebuild_source_maps', 'rebuild_embeddings', 'backfill_page_labels')),
  check(status in ('queued', 'running', 'succeeded', 'failed'))
);

create table if not exists chat_threads (
  id text primary key,
  title text,
  active_source_set_id text references source_sets(id),
  created_at text not null,
  updated_at text not null
);

create table if not exists chat_thread_source_books (
  thread_id text not null references chat_threads(id) on delete cascade,
  book_id text not null references books(id) on delete cascade,
  source_set_id text references source_sets(id) on delete set null,
  captured_at text not null,
  primary key(thread_id, book_id)
);

create table if not exists chat_messages (
  id text primary key,
  thread_id text not null references chat_threads(id) on delete cascade,
  role text not null,
  content text not null,
  created_at text not null,
  metadata_json text not null default '{}',
  check(role in ('user', 'assistant', 'system', 'tool'))
);

create table if not exists retrieval_runs (
  id text primary key,
  thread_id text references chat_threads(id),
  message_id text references chat_messages(id),
  source_set_id text references source_sets(id),
  query text not null,
  created_at text not null,
  metadata_json text not null default '{}'
);

create table if not exists retrieval_run_source_books (
  retrieval_run_id text not null references retrieval_runs(id) on delete cascade,
  source_set_id text references source_sets(id) on delete set null,
  book_id text not null references books(id) on delete cascade,
  book_title_snapshot text not null,
  captured_at text not null,
  primary key(retrieval_run_id, book_id)
);

create table if not exists retrieval_hits (
  id text primary key,
  retrieval_run_id text not null references retrieval_runs(id) on delete cascade,
  page_id text not null references pages(id),
  source_object_id text references source_objects(id) on delete set null,
  score real not null,
  rank integer not null,
  snippet text,
  object_type_snapshot text,
  title_snapshot text,
  heading_path_snapshot_json text not null default '[]',
  confidence_snapshot real,
  rank_reasons_json text not null default '[]',
  text_snapshot_sha256 text,
  metadata_json text not null default '{}',
  check(confidence_snapshot is null or (confidence_snapshot >= 0 and confidence_snapshot <= 1))
);

create table if not exists model_runs (
  id text primary key,
  thread_id text not null references chat_threads(id) on delete cascade,
  user_message_id text references chat_messages(id) on delete set null,
  assistant_message_id text references chat_messages(id) on delete set null,
  retrieval_run_id text references retrieval_runs(id) on delete set null,
  retry_of_model_run_id text references model_runs(id) on delete set null,
  provider text not null,
  model text not null,
  status text not null,
  idempotency_key text not null unique,
  provider_response_id text,
  error_code text,
  error_message text,
  input_tokens integer,
  output_tokens integer,
  created_at text not null,
  updated_at text not null,
  completed_at text,
  metadata_json text not null default '{}',
  check(provider in ('openai', 'fake', 'local')),
  check(status in ('queued', 'retrieving', 'calling_model', 'completed', 'failed')),
  check(status = 'queued' or user_message_id is not null)
);

create index if not exists ix_books_folder_id on books(folder_id);
create index if not exists ix_books_category on books(category);
create index if not exists ix_pages_book_page on pages(book_id, page_number);
create index if not exists ix_page_search_book on page_search(book_id);
create index if not exists ix_source_set_books_book on source_set_books(book_id);
create index if not exists ix_page_assets_page on page_assets(page_id);
create index if not exists ix_page_assets_book_label_lookup
on page_assets(book_id, page_number, kind);
create index if not exists ix_asset_labels_asset on asset_labels(asset_id);
create index if not exists ix_source_objects_book_type
on source_objects(book_id, object_type);
create index if not exists ix_source_objects_page
on source_objects(page_id);
create index if not exists ix_source_objects_parent
on source_objects(parent_object_id);
create index if not exists ix_source_object_links_from
on source_object_links(from_object_id);
create index if not exists ix_source_object_links_to_object
on source_object_links(to_object_id);
create index if not exists ix_book_query_profiles_query_type
on book_query_profiles(query_type);
create index if not exists ix_retrieval_run_source_books_book
on retrieval_run_source_books(book_id, captured_at);
create index if not exists ix_source_object_search_book_type
on source_object_search(book_id, object_type);
create index if not exists ix_book_page_label_calibrations_status
on book_page_label_calibrations(status, updated_at);
create index if not exists ix_ingest_jobs_status on ingest_jobs(status, job_type);
create index if not exists ix_chat_threads_updated_at on chat_threads(updated_at desc);
create index if not exists ix_chat_thread_source_books_book
on chat_thread_source_books(book_id);
create index if not exists ix_chat_messages_thread_created
on chat_messages(thread_id, created_at, id);
create index if not exists ix_retrieval_runs_thread_message
on retrieval_runs(thread_id, message_id, created_at);
create unique index if not exists ux_retrieval_hits_run_rank
on retrieval_hits(retrieval_run_id, rank);
create unique index if not exists ux_retrieval_hits_run_source_object
on retrieval_hits(retrieval_run_id, source_object_id)
where source_object_id is not null;
create unique index if not exists ux_retrieval_hits_run_page_fallback
on retrieval_hits(retrieval_run_id, page_id)
where source_object_id is null;
create index if not exists ix_model_runs_thread_status
on model_runs(thread_id, status, updated_at);
create index if not exists ix_model_runs_user_message on model_runs(user_message_id);
create index if not exists ix_model_runs_retry_of on model_runs(retry_of_model_run_id);
create unique index if not exists ux_model_runs_one_active_retry
on model_runs(retry_of_model_run_id)
where retry_of_model_run_id is not null
  and status in ('queued', 'retrieving', 'calling_model');

create view if not exists book_readiness as
select
  id as book_id,
  case
    when copy_status = 'copied' then 1
    else 0
  end as reader_ready,
  case
    when copy_status = 'copied'
      and text_status = 'imported'
      and search_status = 'indexed'
    then 1
    else 0
  end as search_ready,
  case
    when copy_status = 'copied'
      and text_status = 'imported'
      and search_status = 'indexed'
      and visual_status = 'scanned'
    then 1
    else 0
  end as fully_ready,
  case
    when copy_status in ('managed_missing', 'failed')
      or text_status = 'failed'
      or search_status = 'failed'
      or visual_status = 'failed'
    then 1
    else 0
  end as needs_attention
from books;

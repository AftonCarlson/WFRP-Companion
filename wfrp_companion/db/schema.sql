create table if not exists app_settings (
  key text primary key,
  value_json text not null,
  updated_at text not null
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
  check(job_type in ('copy_pdf', 'import_page_text', 'rebuild_fts', 'scan_visual_assets', 'render_page')),
  check(status in ('queued', 'running', 'succeeded', 'failed'))
);

create table if not exists chat_threads (
  id text primary key,
  title text,
  active_source_set_id text references source_sets(id),
  created_at text not null,
  updated_at text not null
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

create table if not exists retrieval_hits (
  retrieval_run_id text not null references retrieval_runs(id) on delete cascade,
  page_id text not null references pages(id),
  score real not null,
  rank integer not null,
  snippet text,
  primary key(retrieval_run_id, page_id)
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
create index if not exists ix_ingest_jobs_status on ingest_jobs(status, job_type);

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

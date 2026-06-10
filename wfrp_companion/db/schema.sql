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
  structured_evidence_status text not null default 'not_started',
  page_text_snapshot_sha256 text,
  source_object_snapshot_sha256 text,
  source_map_snapshot_sha256 text,
  vector_snapshot_sha256 text,
  structured_evidence_snapshot_sha256 text,
  source_map_started_at text,
  vector_started_at text,
  table_index_started_at text,
  page_label_started_at text,
  structured_evidence_started_at text,
  structured_evidence_last_review_at text,
  embedding_provider text,
  embedding_model text,
  embedding_dimensions integer,
  last_error text,
  updated_at text not null,
  check(source_map_status in ('not_started', 'indexing', 'indexed', 'needs_refresh', 'failed')),
  check(table_index_status in ('not_started', 'indexing', 'indexed', 'needs_refresh', 'failed', 'disabled')),
  check(vector_status in ('not_started', 'indexing', 'indexed', 'needs_refresh', 'failed', 'disabled')),
  check(page_label_status in ('not_started', 'calibrating', 'calibrated', 'needs_review', 'failed')),
  check(structured_evidence_status in ('not_started', 'extracting', 'indexed', 'needs_review', 'needs_refresh', 'failed', 'disabled')),
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

create table if not exists structured_reader_observations (
  id text primary key,
  book_id text not null references books(id) on delete cascade,
  page_id text not null references pages(id) on delete cascade,
  page_number integer not null,
  source_object_id text references source_objects(id) on delete set null,
  reader_name text not null,
  reader_version text not null,
  observation_type text not null,
  object_shape text,
  content_kind text,
  entity_kind text,
  title text,
  table_number text,
  canonical_name text,
  char_start integer,
  char_end integer,
  bbox_json text,
  payload_json text not null default '{}',
  text_hash text,
  text_snapshot_sha256 text not null,
  confidence real not null,
  created_at text not null,
  check(reader_name in ('page_text_import', 'source_object_heuristic', 'pymupdf_text', 'pymupdf_words', 'tesseract_ocr', 'manual_seed')),
  check(observation_type in ('table_caption', 'table_region', 'table_row', 'profile_header', 'profile_stat_block', 'profile_field_block', 'cross_reference', 'page_reference', 'layout_metadata')),
  check(object_shape is null or object_shape in ('structured_table', 'table_row', 'profile_bundle', 'profile_field_block')),
  check(content_kind is null or content_kind in ('rules_table', 'combat_table', 'equipment_table', 'random_roll_table', 'encounter_table', 'career_table', 'spell_table', 'creature_profile', 'npc_profile', 'generic_stat_block', 'unknown')),
  check(entity_kind is null or entity_kind in ('monster', 'npc', 'creature', 'item', 'spell', 'career', 'rule', 'location', 'none', 'unknown')),
  check(confidence >= 0 and confidence <= 1),
  check(page_number >= 1),
  check(char_start is null or char_start >= 0),
  check(char_end is null or char_start is null or char_end >= char_start)
);

create table if not exists structured_evidence_candidates (
  id text primary key,
  book_id text not null references books(id) on delete cascade,
  primary_page_id text not null references pages(id) on delete cascade,
  primary_source_object_id text references source_objects(id) on delete set null,
  object_shape text not null,
  content_kind text not null,
  entity_kind text not null,
  canonical_name text,
  title text,
  table_number text,
  table_number_normalized text,
  page_start integer not null,
  page_end integer not null,
  printed_page_start text,
  printed_page_end text,
  heading_path_json text not null default '[]',
  observation_ids_json text not null default '[]',
  source_object_ids_json text not null default '[]',
  payload_json text not null,
  search_text text not null,
  confidence real not null,
  suspicious_flags_json text not null default '[]',
  status text not null,
  status_reason text,
  text_snapshot_sha256 text not null,
  structured_extractor_version text not null,
  created_at text not null,
  updated_at text not null,
  check(status in ('candidate', 'needs_review', 'auto_rejected', 'approved', 'corrected', 'rejected', 'superseded')),
  check(object_shape in ('structured_table', 'profile_bundle')),
  check(confidence >= 0 and confidence <= 1),
  check(page_start >= 1),
  check(page_end >= page_start)
);

create table if not exists validated_structured_objects (
  id text primary key,
  candidate_id text references structured_evidence_candidates(id) on delete set null,
  book_id text not null references books(id) on delete cascade,
  primary_page_id text not null references pages(id) on delete cascade,
  primary_source_object_id text references source_objects(id) on delete set null,
  object_shape text not null,
  content_kind text not null,
  entity_kind text not null,
  canonical_name text,
  title text,
  table_number text,
  table_number_normalized text,
  page_start integer not null,
  page_end integer not null,
  printed_page_start text,
  printed_page_end text,
  heading_path_json text not null default '[]',
  payload_schema_version integer not null,
  payload_json text not null,
  field_confidence_json text not null default '{}',
  source_snapshot_sha256 text not null,
  validation_status text not null,
  review_state text not null,
  created_at text not null,
  updated_at text not null,
  reviewed_at text,
  check(validation_status in ('active', 'stale', 'retired')),
  check(review_state in ('auto_approved', 'human_approved', 'human_corrected')),
  check(payload_schema_version >= 1),
  check(object_shape in ('structured_table', 'profile_bundle')),
  check(page_start >= 1),
  check(page_end >= page_start)
);

create table if not exists validated_structured_object_sources (
  id text primary key,
  validated_object_id text not null references validated_structured_objects(id) on delete cascade,
  anchor_kind text not null,
  source_object_id text references source_objects(id) on delete cascade,
  page_id text references pages(id) on delete cascade,
  source_role text not null,
  source_snapshot_sha256 text not null,
  confidence real not null,
  created_at text not null,
  check(anchor_kind in ('source_object', 'page', 'manual')),
  check(source_role in ('primary', 'fallback_page', 'supporting_section', 'stat_block', 'profile_text', 'table_row', 'manual_correction')),
  check(
    (anchor_kind = 'source_object' and source_object_id is not null and page_id is null)
    or (anchor_kind = 'page' and source_object_id is null and page_id is not null)
    or (anchor_kind = 'manual' and source_object_id is null and page_id is null)
  ),
  check(confidence >= 0 and confidence <= 1)
);

create table if not exists validated_structured_object_aliases (
  validated_object_id text not null references validated_structured_objects(id) on delete cascade,
  book_id text not null references books(id) on delete cascade,
  alias text not null,
  alias_normalized text not null,
  alias_source text not null,
  confidence real not null,
  created_at text not null,
  primary key(validated_object_id, alias_normalized),
  check(alias_source in ('canonical', 'title', 'table_number', 'generated_plural', 'generated_word_order', 'manual')),
  check(confidence >= 0 and confidence <= 1),
  check(length(alias_normalized) > 0)
);

create table if not exists structured_evidence_reviews (
  id text primary key,
  candidate_id text references structured_evidence_candidates(id) on delete set null,
  validated_object_id text references validated_structured_objects(id) on delete set null,
  action text not null,
  reviewer text,
  notes text,
  patch_json text not null default '{}',
  prior_payload_hash text,
  after_payload_hash text,
  created_at text not null,
  check(action in ('approve', 'correct', 'reject', 'mark_stale', 'retire', 'restore'))
);

create trigger if not exists structured_evidence_reviews_no_update
after update on structured_evidence_reviews
begin
  select raise(abort, 'structured_evidence_reviews is append-only');
end;

create trigger if not exists structured_evidence_reviews_no_delete
after delete on structured_evidence_reviews
begin
  select raise(abort, 'structured_evidence_reviews is append-only');
end;

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
  check(job_type in ('copy_pdf', 'import_page_text', 'rebuild_fts', 'scan_visual_assets', 'render_page', 'extract_source_objects', 'rebuild_source_object_fts', 'rebuild_source_maps', 'rebuild_embeddings', 'backfill_page_labels', 'extract_structured_evidence', 'rebuild_structured_evidence_search')),
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

create table if not exists chat_thread_context (
  thread_id text primary key references chat_threads(id) on delete cascade,
  active_subject text,
  active_intent text,
  active_book_id text references books(id) on delete set null,
  active_printed_page_label text,
  active_pdf_page_number integer,
  active_source_object_id text references source_objects(id) on delete set null,
  updated_from_message_id text references chat_messages(id) on delete set null,
  updated_from_model_run_id text references model_runs(id) on delete set null,
  metadata_json text not null default '{}',
  updated_at text not null,
  check(active_pdf_page_number is null or active_pdf_page_number >= 1)
);

create table if not exists familiar_research_runs (
  id text primary key,
  model_run_id text not null unique references model_runs(id) on delete cascade,
  thread_id text not null references chat_threads(id) on delete cascade,
  user_message_id text not null references chat_messages(id) on delete cascade,
  source_set_id text references source_sets(id) on delete set null,
  raw_query text not null,
  resolved_query text not null,
  intent text not null,
  status text not null,
  max_tool_rounds integer not null,
  tool_rounds_used integer not null default 0,
  evidence_status text not null,
  final_retrieval_run_id text references retrieval_runs(id) on delete set null,
  metadata_json text not null default '{}',
  created_at text not null,
  updated_at text not null,
  completed_at text,
  check(status in (
    'planning',
    'tool_calling',
    'validating',
    'deciding',
    'finalizing',
    'completed',
    'insufficient',
    'failed'
  )),
  check(evidence_status in (
    'not_evaluated',
    'sufficient',
    'partial',
    'insufficient'
  )),
  check(max_tool_rounds > 0),
  check(tool_rounds_used >= 0),
  check(tool_rounds_used <= max_tool_rounds)
);

create table if not exists familiar_turn_decisions (
  id text primary key,
  model_run_id text not null unique references model_runs(id) on delete cascade,
  thread_id text not null references chat_threads(id) on delete cascade,
  user_message_id text not null references chat_messages(id) on delete cascade,
  retry_of_decision_id text references familiar_turn_decisions(id) on delete set null,
  turn_kind text not null,
  answer_mode text not null,
  subject text,
  confidence text not null,
  reasons_json text not null default '[]',
  reader_context_policy text not null,
  answer_outcome text,
  outcome_json text not null default '{}',
  metadata_json text not null default '{}',
  created_at text not null,
  updated_at text not null,
  check(turn_kind in (
    'conversation',
    'app_help',
    'rules_lookup',
    'statline_lookup',
    'source_navigation',
    'lore_lookup',
    'scene_prep',
    'clarification_needed'
  )),
  check(answer_mode in ('direct', 'research', 'clarify')),
  check(confidence in ('high', 'medium', 'low')),
  check(reader_context_policy in (
    'ignore',
    'routing_hint',
    'page_navigation_hint'
  )),
  check(answer_outcome is null or answer_outcome in (
    'direct_response',
    'full_answer',
    'partial_answer',
    'clarifying_question',
    'insufficient_evidence',
    'provider_error'
  ))
);

create table if not exists familiar_research_plans (
  id text primary key,
  research_run_id text not null references familiar_research_runs(id) on delete cascade,
  revision integer not null,
  status text not null,
  intent text not null,
  plan_summary text not null,
  subject_json text not null default '{}',
  requirements_json text not null default '[]',
  planned_actions_json text not null default '[]',
  provider_call_id text,
  validation_errors_json text not null default '[]',
  created_at text not null,
  updated_at text not null,
  check(revision >= 1),
  check(status in ('proposed', 'accepted', 'rejected', 'superseded')),
  check(length(intent) > 0),
  check(length(plan_summary) > 0)
);

create table if not exists familiar_tool_calls (
  id text primary key,
  research_run_id text not null references familiar_research_runs(id) on delete cascade,
  research_plan_id text references familiar_research_plans(id) on delete set null,
  requirement_id text,
  purpose text,
  step_number integer not null,
  call_index integer not null default 0,
  provider_call_id text,
  tool_name text not null,
  arguments_json text not null,
  argument_hash text not null,
  status text not null,
  retrieval_run_id text references retrieval_runs(id) on delete set null,
  output_summary_json text not null default '{}',
  error_code text,
  error_message text,
  created_at text not null,
  updated_at text not null,
  completed_at text,
  check(status in ('requested', 'running', 'succeeded', 'failed', 'rejected')),
  check(step_number >= 1),
  check(call_index >= 0),
  check(length(tool_name) > 0),
  check(length(argument_hash) > 0)
);

create table if not exists familiar_evidence_judgments (
  id text primary key,
  research_run_id text not null references familiar_research_runs(id) on delete cascade,
  research_plan_id text references familiar_research_plans(id) on delete set null,
  requirement_id text,
  retrieval_run_id text references retrieval_runs(id) on delete set null,
  retrieval_hit_id text references retrieval_hits(id) on delete set null,
  source_object_id text references source_objects(id) on delete set null,
  book_id text references books(id) on delete set null,
  printed_page_label text,
  requirement_type text not null,
  status text not null,
  reason_code text not null,
  reasons_json text not null default '[]',
  subject_constraint_json text not null default '{}',
  constraint_status text,
  created_at text not null,
  check(status in ('accepted', 'rejected', 'partial')),
  check(length(requirement_type) > 0),
  check(length(reason_code) > 0)
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
create index if not exists ix_familiar_turn_decisions_thread
on familiar_turn_decisions(thread_id, created_at);
create index if not exists ix_familiar_turn_decisions_retry
on familiar_turn_decisions(retry_of_decision_id);
create index if not exists ix_familiar_research_runs_model_run
on familiar_research_runs(model_run_id);
create index if not exists ix_familiar_research_runs_thread
on familiar_research_runs(thread_id, created_at);
create unique index if not exists ux_familiar_research_plans_run_revision
on familiar_research_plans(research_run_id, revision);
create unique index if not exists ux_familiar_research_plans_accepted_run
on familiar_research_plans(research_run_id)
where status = 'accepted';
create index if not exists ix_familiar_research_plans_run_status
on familiar_research_plans(research_run_id, status);
create index if not exists ix_familiar_tool_calls_run
on familiar_tool_calls(research_run_id, step_number);
create unique index if not exists ux_familiar_tool_calls_step_call
on familiar_tool_calls(research_run_id, step_number, call_index);
create unique index if not exists ux_familiar_tool_calls_provider_call
on familiar_tool_calls(research_run_id, provider_call_id)
where provider_call_id is not null;
create index if not exists ix_familiar_tool_calls_retrieval
on familiar_tool_calls(retrieval_run_id);
create index if not exists ix_familiar_tool_calls_plan_requirement
on familiar_tool_calls(research_plan_id, requirement_id, step_number);
create index if not exists ix_familiar_evidence_judgments_run
on familiar_evidence_judgments(research_run_id, status);
create index if not exists ix_familiar_evidence_judgments_hit
on familiar_evidence_judgments(retrieval_hit_id);
create index if not exists ix_familiar_evidence_judgments_requirement
on familiar_evidence_judgments(research_plan_id, requirement_id, status);
create index if not exists ix_structured_reader_observations_book_page
on structured_reader_observations(book_id, page_number, reader_name);
create index if not exists ix_structured_reader_observations_source_object
on structured_reader_observations(source_object_id);
create index if not exists ix_structured_reader_observations_type
on structured_reader_observations(book_id, observation_type, object_shape);
create index if not exists ix_structured_candidates_book_status
on structured_evidence_candidates(book_id, status, updated_at);
create index if not exists ix_structured_candidates_lookup
on structured_evidence_candidates(
  book_id,
  object_shape,
  table_number_normalized,
  canonical_name
);
create index if not exists ix_structured_candidates_page
on structured_evidence_candidates(book_id, page_start, page_end);
create unique index if not exists ux_structured_candidates_active_identity
on structured_evidence_candidates(
  book_id,
  object_shape,
  coalesce(table_number_normalized, ''),
  coalesce(canonical_name, ''),
  page_start,
  text_snapshot_sha256,
  structured_extractor_version
)
where status not in ('auto_rejected', 'rejected', 'superseded');
create index if not exists ix_validated_structured_objects_book_shape
on validated_structured_objects(book_id, object_shape, validation_status);
create index if not exists ix_validated_structured_objects_table_number
on validated_structured_objects(
  book_id,
  table_number_normalized,
  validation_status
);
create index if not exists ix_validated_structured_objects_name
on validated_structured_objects(book_id, canonical_name, validation_status);
create unique index if not exists ux_validated_structured_objects_active_table
on validated_structured_objects(book_id, object_shape, table_number_normalized)
where validation_status = 'active'
  and table_number_normalized is not null;
create unique index if not exists ux_validated_structured_objects_active_profile
on validated_structured_objects(book_id, object_shape, canonical_name, entity_kind)
where validation_status = 'active'
  and canonical_name is not null;
create unique index if not exists ux_validated_sources_source_object
on validated_structured_object_sources(
  validated_object_id,
  source_role,
  source_object_id
)
where anchor_kind = 'source_object';
create unique index if not exists ux_validated_sources_page
on validated_structured_object_sources(validated_object_id, source_role, page_id)
where anchor_kind = 'page';
create index if not exists ix_validated_sources_role
on validated_structured_object_sources(
  validated_object_id,
  source_role,
  anchor_kind
);
create index if not exists ix_validated_alias_lookup
on validated_structured_object_aliases(
  book_id,
  alias_normalized,
  confidence desc
);
create index if not exists ix_validated_alias_object
on validated_structured_object_aliases(validated_object_id);

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

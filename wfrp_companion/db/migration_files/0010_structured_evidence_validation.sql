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

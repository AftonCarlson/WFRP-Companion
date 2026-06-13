create table if not exists structured_visual_regions (
  id text primary key,
  book_id text not null references books(id) on delete cascade,
  source_snapshot_sha256 text not null,
  ingest_job_id text references ingest_jobs(id) on delete set null,
  provider_name text not null,
  provider_version text not null default '',
  pdf_page_start integer not null,
  pdf_page_end integer not null,
  printed_page_start text,
  printed_page_end text,
  region_kind text not null,
  bbox_json text not null,
  crop_asset_path text,
  raw_text text not null default '',
  confidence real not null default 0,
  issues_json text not null default '[]',
  created_at text not null default current_timestamp,
  check(region_kind in ('table', 'profile_card', 'career_entry', 'rules_entry', 'heading', 'text_block', 'stat_grid', 'unknown')),
  check(pdf_page_start >= 1),
  check(pdf_page_end >= pdf_page_start),
  check(confidence >= 0 and confidence <= 1)
);

create index if not exists ix_structured_visual_regions_lookup
on structured_visual_regions(
  book_id,
  source_snapshot_sha256,
  pdf_page_start,
  region_kind
);

create table if not exists structured_envelopes (
  id text primary key,
  book_id text not null references books(id) on delete cascade,
  source_snapshot_sha256 text not null,
  envelope_kind text not null,
  scope_kind text not null default 'book',
  scope_value text not null default '',
  identity_raw text not null default '',
  identity_normalized text not null default '',
  parent_envelope_id text references structured_envelopes(id) on delete set null,
  pdf_page_start integer not null,
  pdf_page_end integer not null,
  printed_page_start text,
  printed_page_end text,
  confidence real not null default 0,
  status text not null default 'candidate',
  issues_json text not null default '[]',
  created_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  check(envelope_kind in ('profile_card', 'career_entry', 'rules_entry', 'structured_table')),
  check(scope_kind in ('book', 'chapter', 'section', 'page', 'parent_object', 'location')),
  check(status in ('candidate', 'needs_review', 'validated', 'rejected', 'superseded', 'blocked')),
  check(pdf_page_start >= 1),
  check(pdf_page_end >= pdf_page_start),
  check(confidence >= 0 and confidence <= 1)
);

create index if not exists ix_structured_envelopes_status
on structured_envelopes(book_id, source_snapshot_sha256, envelope_kind, status);

create index if not exists ix_structured_envelopes_identity
on structured_envelopes(
  book_id,
  envelope_kind,
  identity_normalized,
  scope_kind,
  scope_value
);

create unique index if not exists ux_structured_envelopes_active_top_level
on structured_envelopes(
  book_id,
  envelope_kind,
  identity_normalized,
  scope_kind,
  scope_value,
  source_snapshot_sha256
)
where status in ('candidate', 'needs_review', 'validated')
  and parent_envelope_id is null;

create table if not exists structured_envelope_regions (
  envelope_id text not null references structured_envelopes(id) on delete cascade,
  visual_region_id text not null references structured_visual_regions(id) on delete cascade,
  role text not null,
  ordinal integer not null default 0,
  primary key(envelope_id, visual_region_id, role),
  check(role in ('primary', 'heading', 'body', 'stat_grid', 'table', 'caption', 'footnote', 'supporting'))
);

create index if not exists ix_structured_envelope_regions_region
on structured_envelope_regions(visual_region_id);

create table if not exists structured_envelope_source_objects (
  envelope_id text not null references structured_envelopes(id) on delete cascade,
  source_object_id text not null references source_objects(id) on delete cascade,
  role text not null,
  ordinal integer not null default 0,
  primary key(envelope_id, source_object_id, role),
  check(role in ('primary', 'heading', 'body', 'stat_block', 'table', 'table_row', 'profile_text', 'supporting', 'reference'))
);

create index if not exists ix_structured_envelope_source_objects_source
on structured_envelope_source_objects(source_object_id);

create table if not exists structured_review_actions (
  id text primary key,
  candidate_id text references structured_evidence_candidates(id) on delete set null,
  envelope_id text references structured_envelopes(id) on delete set null,
  validated_object_id text references validated_structured_objects(id) on delete set null,
  action_kind text not null,
  action_payload_json text not null,
  reviewer text not null default 'local_user',
  created_at text not null default current_timestamp,
  check(action_kind in ('approve', 'reject', 'correct_fields', 'reclassify', 'merge', 'split', 'set_parent', 'clear_parent', 'mark_suspicious', 'rerun_reader'))
);

create index if not exists ix_structured_review_actions_candidate
on structured_review_actions(candidate_id, created_at);

create index if not exists ix_structured_review_actions_envelope
on structured_review_actions(envelope_id, created_at);

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

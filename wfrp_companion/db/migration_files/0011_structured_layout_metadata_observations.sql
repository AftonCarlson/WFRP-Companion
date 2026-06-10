alter table structured_reader_observations
rename to structured_reader_observations_before_0011;

create table structured_reader_observations (
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

insert into structured_reader_observations (
  id,
  book_id,
  page_id,
  page_number,
  source_object_id,
  reader_name,
  reader_version,
  observation_type,
  object_shape,
  content_kind,
  entity_kind,
  title,
  table_number,
  canonical_name,
  char_start,
  char_end,
  bbox_json,
  payload_json,
  text_hash,
  text_snapshot_sha256,
  confidence,
  created_at
)
select
  id,
  book_id,
  page_id,
  page_number,
  source_object_id,
  reader_name,
  reader_version,
  observation_type,
  object_shape,
  content_kind,
  entity_kind,
  title,
  table_number,
  canonical_name,
  char_start,
  char_end,
  bbox_json,
  payload_json,
  text_hash,
  text_snapshot_sha256,
  confidence,
  created_at
from structured_reader_observations_before_0011;

drop table structured_reader_observations_before_0011;

create index if not exists ix_structured_reader_observations_book_page
on structured_reader_observations(book_id, page_number, reader_name);

create index if not exists ix_structured_reader_observations_source_object
on structured_reader_observations(source_object_id);

create index if not exists ix_structured_reader_observations_type
on structured_reader_observations(book_id, observation_type, object_shape);

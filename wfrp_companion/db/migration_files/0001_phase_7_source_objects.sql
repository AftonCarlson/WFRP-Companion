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
  last_error text,
  updated_at text not null,
  check(status in ('not_started', 'extracting', 'extracted', 'indexing', 'indexed', 'failed')),
  check(object_count >= 0),
  check(table_count >= 0),
  check(stat_block_count >= 0),
  check(location_count >= 0)
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

create index if not exists ix_source_object_search_book_type
on source_object_search(book_id, object_type);

create table if not exists source_object_embeddings (
  id text primary key,
  source_object_id text not null references source_objects(id) on delete cascade,
  book_id text not null references books(id) on delete cascade,
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
  embedding_model,
  embedding_dimensions,
  text_snapshot_sha256
);

create index if not exists ix_source_object_embeddings_book_model
on source_object_embeddings(book_id, embedding_model, embedding_dimensions);

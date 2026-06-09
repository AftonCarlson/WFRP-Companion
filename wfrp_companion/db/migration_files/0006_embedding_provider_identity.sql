drop index if exists ux_source_object_embeddings_current;

create unique index if not exists ux_source_object_embeddings_current
on source_object_embeddings(
  source_object_id,
  embedding_provider,
  embedding_model,
  embedding_dimensions,
  text_snapshot_sha256
);

drop index if exists ix_source_object_embeddings_book_model;

create index if not exists ix_source_object_embeddings_book_model
on source_object_embeddings(
  book_id,
  embedding_provider,
  embedding_model,
  embedding_dimensions
);

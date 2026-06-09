from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import retrieval_status
from wfrp_companion.library import source_sets
from wfrp_companion.source_objects.embeddings import embedding_source_snapshot_sha256
from wfrp_companion.source_objects.embeddings import source_object_embedding_id
from wfrp_companion.source_objects.embeddings import vector_blob


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def local_hash_config(tmp_path: Path) -> AppConfig:
    return replace(
        make_config(tmp_path),
        embedding_provider="local-hash",
        embedding_model="local-hash-test",
        embedding_dimensions=4,
    )


def seed_book(
    config: AppConfig,
    *,
    book_id: str,
    category: str = "Rules and Mechanics Toolkits",
    object_type: str = "stat_block",
    title: str | None = None,
) -> None:
    selected_title = title or book_id.replace("-", " ").title()
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path, sort_order)
            values ('core', null, 'Core', 'Core', 0)
            on conflict(id) do nothing
            """
        )
        connection.execute(
            """
            insert into books (
              id,
              folder_id,
              title,
              category,
              relative_path,
              original_source_path,
              managed_pdf_path,
              original_sha256,
              managed_sha256,
              page_count,
              copy_status,
              text_status,
              search_status,
              visual_status,
              discovered_at,
              updated_at
            )
            values (?, 'core', ?, ?, ?, ?, ?, ?, ?, 1, 'copied', 'imported',
                    'indexed', 'not_scanned', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """,
            (
                book_id,
                selected_title,
                category,
                f"{category}/{selected_title}.pdf",
                f"/source/{book_id}.pdf",
                f"/managed/{book_id}.pdf",
                f"sha-{book_id}",
                f"sha-{book_id}",
            ),
        )
        connection.execute(
            """
            insert into pages (
              id,
              book_id,
              page_number,
              extraction_method,
              embedded_text_chars,
              text_chars,
              word_count,
              image_count,
              ocr_attempted,
              has_text
            )
            values (?, ?, 1, 'ocr', 0, 40, 6, 0, 1, 1)
            """,
            (f"{book_id}:1", book_id),
        )
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values (?, ?, ?, '2026-06-09T00:00:00Z')
            """,
            (
                f"{book_id}:1",
                f"{selected_title} stat_block: M 4 WS 31.",
                f"sha-text-{book_id}",
            ),
        )
        connection.execute(
            """
            insert into source_objects (
              id,
              book_id,
              page_id,
              object_type,
              parent_object_id,
              title,
              heading_path_json,
              page_start,
              page_end,
              char_start,
              char_end,
              bbox_json,
              text,
              search_text,
              metadata_json,
              confidence,
              extraction_method,
              text_snapshot_sha256,
              created_at,
              updated_at
            )
            values (?, ?, ?, ?, null, ?, '[]', 1, 1, null, null, null, ?, ?,
                    '{}', 0.95, 'synthetic', ?, '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """,
            (
                f"{book_id}:object",
                book_id,
                f"{book_id}:1",
                object_type,
                selected_title,
                f"{selected_title} stat_block: M 4 WS 31.",
                f"{selected_title} stat_block: M 4 WS 31.",
                f"sha-object-{book_id}",
            ),
        )
        connection.execute(
            """
            insert into book_object_status (
              book_id,
              status,
              object_count,
              table_count,
              stat_block_count,
              location_count,
              text_snapshot_sha256,
              extractor_version,
              updated_at
            )
            values (?, 'indexed', 1, ?, ?, 0, ?, 'synthetic',
                    '2026-06-09T00:00:00Z')
            """,
            (
                book_id,
                1 if object_type in {"table", "table_row"} else 0,
                1 if object_type in {"stat_block", "monster_profile", "npc_profile"} else 0,
                f"sha-object-{book_id}",
            ),
        )


def mark_vector_status(
    config: AppConfig,
    *,
    book_id: str,
    status: str,
) -> None:
    with initialize_database(config.db_path) as connection:
        snapshot = embedding_source_snapshot_sha256(connection, book_id)
        connection.execute(
            """
            insert into book_retrieval_status (
              book_id,
              source_map_status,
              table_index_status,
              vector_status,
              page_label_status,
              source_object_snapshot_sha256,
              vector_snapshot_sha256,
              embedding_provider,
              embedding_model,
              embedding_dimensions,
              updated_at
            )
            values (?, 'indexed', 'indexed', ?, 'calibrated', ?, ?, ?, ?, ?,
                    '2026-06-09T00:00:00Z')
            on conflict(book_id) do update set
              vector_status = excluded.vector_status,
              vector_snapshot_sha256 = excluded.vector_snapshot_sha256,
              embedding_provider = excluded.embedding_provider,
              embedding_model = excluded.embedding_model,
              embedding_dimensions = excluded.embedding_dimensions,
              updated_at = excluded.updated_at
            """,
            (
                book_id,
                status,
                snapshot,
                snapshot,
                config.embedding_provider,
                config.embedding_model,
                config.embedding_dimensions,
            ),
        )
        if status == "indexed":
            connection.execute(
                """
                insert into source_object_embeddings (
                  id,
                  source_object_id,
                  book_id,
                  embedding_provider,
                  embedding_model,
                  embedding_dimensions,
                  text_snapshot_sha256,
                  vector_blob,
                  created_at,
                  updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, '2026-06-09T00:00:00Z',
                        '2026-06-09T00:00:00Z')
                """,
                (
                    source_object_embedding_id(
                        f"{book_id}:object",
                        config.embedding_provider,
                        config.embedding_model,
                        config.embedding_dimensions,
                        f"sha-object-{book_id}",
                    ),
                    f"{book_id}:object",
                    book_id,
                    config.embedding_provider,
                    config.embedding_model,
                    config.embedding_dimensions,
                    f"sha-object-{book_id}",
                    vector_blob((1.0, 0.0, 0.0, 0.0)),
                ),
            )


def test_retrieval_status_counts_current_vectorized_enabled_books(
    tmp_path: Path,
) -> None:
    config = local_hash_config(tmp_path)
    seed_book(config, book_id="bestiary")
    source_sets.ensure_builtin_source_sets(config)
    mark_vector_status(config, book_id="bestiary", status="indexed")

    status = retrieval_status.get_retrieval_status(config)

    assert status.books_total == 1
    assert status.books_enabled == 1
    assert status.page_text_indexed == 1
    assert status.source_objects_indexed == 1
    assert status.table_or_stat_indexed == 1
    assert status.vectorized_current == 1
    assert status.vectorized_enabled == 1
    assert status.embedding_provider == "local-hash"
    assert status.embedding_dimensions == 4
    assert status.vector_status == "ready"


def test_retrieval_status_reports_disabled_embeddings(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config, book_id="bestiary")
    source_sets.ensure_builtin_source_sets(config)

    status = retrieval_status.get_retrieval_status(config)

    assert status.vectorized_current == 0
    assert status.vectorized_enabled == 0
    assert status.embedding_provider == "disabled"
    assert status.embedding_dimensions is None
    assert status.vector_status == "disabled"


def test_retrieval_status_handles_no_active_source_set_or_source_objects(
    tmp_path: Path,
) -> None:
    config = local_hash_config(tmp_path)

    status = retrieval_status.get_retrieval_status(config)

    assert status.books_total == 0
    assert status.books_enabled == 0
    assert status.source_objects_indexed == 0
    assert status.vector_status == "missing"


def test_retrieval_status_distinguishes_error_stale_and_missing_vectors(
    tmp_path: Path,
) -> None:
    config = local_hash_config(tmp_path)
    seed_book(config, book_id="error-book")
    seed_book(config, book_id="stale-book")
    seed_book(config, book_id="missing-book")
    source_sets.ensure_builtin_source_sets(config)
    mark_vector_status(config, book_id="error-book", status="failed")
    mark_vector_status(config, book_id="stale-book", status="needs_refresh")

    error_status = retrieval_status.get_retrieval_status(config)

    assert error_status.vector_status == "error"

    with initialize_database(config.db_path) as connection:
        connection.execute(
            "update book_retrieval_status set vector_status = 'indexed' where book_id = ?",
            ("error-book",),
        )
    stale_status = retrieval_status.get_retrieval_status(config)

    assert stale_status.vector_status == "stale"

    with initialize_database(config.db_path) as connection:
        connection.execute(
            "update book_retrieval_status set vector_status = 'indexed' where book_id = ?",
            ("stale-book",),
        )
    missing_status = retrieval_status.get_retrieval_status(config)

    assert missing_status.vector_status == "missing"

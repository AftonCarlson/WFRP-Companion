from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wfrp_companion.api.app import create_app
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets
from wfrp_companion.search.fts import rebuild_global_fts


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_indexed_books(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into library_folders (id, parent_id, name, relative_path, sort_order)
            values ('core', null, 'Core', 'Core', 0)
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
            values (
              'core-rules', 'core', 'Core Rules', 'Core Book & GM Essentials',
              'Core/Core Rules.pdf', '/source/Core Rules.pdf',
              '/managed/Core Rules.pdf', 'source-sha', 'source-sha', 1,
              'copied', 'imported', 'not_indexed', 'not_scanned',
              '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z'
            )
            """
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
            values ('core-rules:1', 'core-rules', 1, 'ocr', 0, 18, 3, 1, 1, 1)
            """
        )
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values (
              'core-rules:1',
              'Critical hit rules',
              'text-sha',
              '2026-06-04T00:00:00Z'
            )
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
            values (
              'adventure-book', 'core', 'Adventure Book',
              'Adventure Modules and Campaigns',
              'Adventure/Adventure Book.pdf', '/source/Adventure Book.pdf',
              '/managed/Adventure Book.pdf', 'adventure-source-sha',
              'adventure-source-sha', 1, 'copied', 'imported', 'not_indexed',
              'not_scanned', '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z'
            )
            """
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
            values ('adventure-book:1', 'adventure-book', 1, 'ocr', 0, 23, 4, 1, 1, 1)
            """
        )
        connection.execute(
            """
            insert into page_text (page_id, text, text_sha256, generated_at)
            values (
              'adventure-book:1',
              'Critical hit adventure',
              'adventure-text-sha',
              '2026-06-04T00:00:00Z'
            )
            """
        )
    rebuild_global_fts(config)


def test_exact_search_defaults_to_active_source_set(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_books(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            "update pages set page_label = '132' where id = 'core-rules:1'"
        )
    client = TestClient(create_app(config))

    response = client.get("/api/search/exact", params={"query": "critical hit"})

    assert response.status_code == 200
    assert response.json()["query"] == "critical hit"
    assert response.json()["scope"] == {
        "label": "active_source_set",
        "source_set_id": "rules-core",
        "book_ids": ["core-rules"],
        "all_books": False,
    }
    assert [hit["book_id"] for hit in response.json()["hits"]] == ["core-rules"]
    assert response.json()["hits"][0]["page_id"] == "core-rules:1"
    assert response.json()["hits"][0]["pdf_page_number"] == 1
    assert response.json()["hits"][0]["page_label"] == "132"
    assert "[Critical]" in response.json()["hits"][0]["snippet"]


def test_exact_search_supports_all_books_named_source_set_and_book_filters(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_books(config)
    client = TestClient(create_app(config))

    all_books = client.get(
        "/api/search/exact",
        params={"query": "critical", "all_books": "true"},
    )
    named = client.get(
        "/api/search/exact",
        params={"query": "critical", "source_set_id": "rules-core"},
    )
    explicit = client.get(
        "/api/search/exact",
        params=[("query", "critical"), ("book_id", "adventure-book")],
    )

    assert all_books.status_code == 200
    assert all_books.json()["scope"]["all_books"] is True
    assert [hit["book_id"] for hit in all_books.json()["hits"]] == [
        "adventure-book",
        "core-rules",
    ]
    assert named.status_code == 200
    assert named.json()["scope"]["label"] == "source_set"
    assert [hit["book_id"] for hit in named.json()["hits"]] == ["core-rules"]
    assert explicit.status_code == 200
    assert explicit.json()["scope"] == {
        "label": "book_ids",
        "source_set_id": None,
        "book_ids": ["adventure-book"],
        "all_books": False,
    }
    assert [hit["book_id"] for hit in explicit.json()["hits"]] == ["adventure-book"]


def test_exact_search_maps_scope_failures_to_http_statuses(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    insert_indexed_books(config)
    client = TestClient(create_app(config))

    conflict = client.get(
        "/api/search/exact",
        params={
            "query": "critical",
            "all_books": "true",
            "source_set_id": "rules-core",
        },
    )
    missing_source_set = client.get(
        "/api/search/exact",
        params={"query": "critical", "source_set_id": "missing-set"},
    )
    missing_book = client.get(
        "/api/search/exact",
        params={"query": "critical", "book_id": "missing-book"},
    )

    with open_connection(config.db_path) as connection:
        connection.execute(
            "delete from app_settings where key = ?",
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        )
        connection.commit()
    missing_active = client.get("/api/search/exact", params={"query": "critical"})

    assert conflict.status_code == 422
    assert missing_source_set.status_code == 404
    assert missing_book.status_code == 404
    assert missing_active.status_code == 409


def test_exact_search_validates_limit_and_keeps_search_readiness_gate(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_indexed_books(config)
    client = TestClient(create_app(config))
    source_sets.set_book_enabled(config, "rules-core", "adventure-book", True)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update books
            set search_status = 'not_indexed'
            where id = 'adventure-book'
            """
        )
        connection.commit()

    invalid_low = client.get(
        "/api/search/exact",
        params={"query": "critical", "limit": "0"},
    )
    invalid_high = client.get(
        "/api/search/exact",
        params={"query": "critical", "limit": "101"},
    )
    response = client.get("/api/search/exact", params={"query": "critical"})

    assert invalid_low.status_code == 422
    assert invalid_high.status_code == 422
    assert response.status_code == 200
    assert response.json()["scope"]["book_ids"] == ["adventure-book", "core-rules"]
    assert [hit["book_id"] for hit in response.json()["hits"]] == ["core-rules"]

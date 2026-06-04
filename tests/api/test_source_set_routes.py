from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from wfrp_companion.api.app import create_app
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database, open_connection
from wfrp_companion.library import source_sets


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def insert_folder(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        insert into library_folders (id, parent_id, name, relative_path, sort_order)
        values ('core', null, 'Core', 'Core', 0)
        on conflict(id) do nothing
        """
    )


def insert_book(
    connection: sqlite3.Connection,
    *,
    book_id: str,
    title: str,
    category: str,
    search_status: str = "indexed",
) -> None:
    insert_folder(connection)
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
        values (?, 'core', ?, ?, ?, ?, ?, ?, ?, 1, 'copied', 'imported', ?,
                'not_scanned', '2026-06-04T00:00:00Z', '2026-06-04T00:00:00Z')
        """,
        (
            book_id,
            title,
            category,
            f"{category}/{title}.pdf",
            f"/source/{book_id}.pdf",
            f"/managed/{book_id}.pdf",
            f"sha-{book_id}",
            f"sha-{book_id}",
            search_status,
        ),
    )


def seed_books(config: AppConfig) -> None:
    with initialize_database(config.db_path) as connection:
        insert_book(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
        )
        insert_book(
            connection,
            book_id="thousand-thrones",
            title="The Thousand Thrones",
            category="Adventure Modules and Campaigns",
            search_status="not_indexed",
        )


def enabled_value(config: AppConfig, book_id: str) -> int:
    with open_connection(config.db_path) as connection:
        return connection.execute(
            """
            select enabled
            from source_set_books
            where source_set_id = ? and book_id = ?
            """,
            (source_sets.RULES_CORE_SOURCE_SET_ID, book_id),
        ).fetchone()[0]


def test_source_set_list_and_active_routes_return_active_marker(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))

    list_response = client.get("/api/source-sets")
    active_response = client.get("/api/source-sets/active")

    assert list_response.status_code == 200
    assert list_response.json() == {
        "active_source_set_id": "rules-core",
        "source_sets": [
            {
                "id": "rules-core",
                "name": "Rules/Core",
                "description": (
                    "Core rules, GM essentials, and rules/mechanics toolkit books."
                ),
                "is_builtin": True,
                "active": True,
            }
        ],
    }
    assert active_response.status_code == 200
    assert active_response.json() == {"source_set_id": "rules-core"}


def test_active_route_returns_409_for_missing_malformed_or_deleted_active_state(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))

    with open_connection(config.db_path) as connection:
        connection.execute(
            "delete from app_settings where key = ?",
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        )
        connection.commit()
    missing = client.get("/api/source-sets/active")
    overview = client.get("/api/source-sets")

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            insert into app_settings (key, value_json, updated_at)
            values (?, '{bad json', '2026-06-04T00:00:00Z')
            on conflict(key) do update set value_json = excluded.value_json
            """,
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        )
        connection.commit()
    malformed = client.get("/api/source-sets/active")

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update app_settings
            set value_json = '"deleted-set"'
            where key = ?
            """,
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        )
        connection.commit()
    deleted = client.get("/api/source-sets/active")

    assert missing.status_code == 409
    assert overview.status_code == 200
    assert overview.json()["active_source_set_id"] is None
    assert overview.json()["source_sets"][0]["active"] is False
    assert malformed.status_code == 409
    assert deleted.status_code == 409


def test_activate_source_set_and_missing_set_statuses(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))

    active = client.put(
        "/api/source-sets/active",
        json={"source_set_id": "rules-core"},
    )
    missing = client.put(
        "/api/source-sets/active",
        json={"source_set_id": "missing-set"},
    )

    assert active.status_code == 200
    assert active.json() == {"source_set_id": "rules-core"}
    assert missing.status_code == 404


def test_source_set_books_list_and_toggle_routes(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))

    list_response = client.get("/api/source-sets/rules-core/books")
    toggle_response = client.put(
        "/api/source-sets/rules-core/books/core-rules",
        json={"enabled": False},
    )
    updated_list_response = client.get("/api/source-sets/rules-core/books")

    assert list_response.status_code == 200
    assert list_response.json() == {
        "source_set_id": "rules-core",
        "books": [
            {
                "source_set_id": "rules-core",
                "book_id": "thousand-thrones",
                "title": "The Thousand Thrones",
                "category": "Adventure Modules and Campaigns",
                "enabled": False,
                "search_ready": False,
            },
            {
                "source_set_id": "rules-core",
                "book_id": "core-rules",
                "title": "Core Rules",
                "category": "Core Book & GM Essentials",
                "enabled": True,
                "search_ready": True,
            },
        ],
    }
    assert toggle_response.status_code == 200
    assert toggle_response.json()["enabled"] is False
    assert enabled_value(config, "core-rules") == 0
    assert updated_list_response.json()["books"][1]["enabled"] is False


def test_source_set_book_routes_map_missing_rows_to_404(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    client = TestClient(create_app(config))

    missing_set_list = client.get("/api/source-sets/missing-set/books")
    missing_set_toggle = client.put(
        "/api/source-sets/missing-set/books/core-rules",
        json={"enabled": True},
    )
    missing_book_toggle = client.put(
        "/api/source-sets/rules-core/books/missing-book",
        json={"enabled": True},
    )

    assert missing_set_list.status_code == 404
    assert missing_set_toggle.status_code == 404
    assert missing_book_toggle.status_code == 404

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

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
            book_id="career-compendium",
            title="Career Compendium",
            category="Rules and Mechanics Toolkits",
        )
        insert_book(
            connection,
            book_id="sigmars-heirs",
            title="Sigmar's Heirs",
            category="World Guides and Faction Sourcebooks",
        )
        insert_book(
            connection,
            book_id="thousand-thrones",
            title="The Thousand Thrones",
            category="Adventure Modules and Campaigns",
            search_status="not_indexed",
        )


def fetch_one(config: AppConfig, query: str, parameters: tuple[object, ...] = ()) -> sqlite3.Row:
    with open_connection(config.db_path) as connection:
        row = connection.execute(query, parameters).fetchone()
    assert row is not None
    return row


def fetch_all(
    config: AppConfig,
    query: str,
    parameters: tuple[object, ...] = (),
) -> list[sqlite3.Row]:
    with open_connection(config.db_path) as connection:
        return connection.execute(query, parameters).fetchall()


def test_ensure_builtin_source_sets_creates_rules_core_and_book_rows(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)

    summary = source_sets.ensure_builtin_source_sets(config)

    source_set = fetch_one(
        config,
        "select * from source_sets where id = ?",
        (source_sets.RULES_CORE_SOURCE_SET_ID,),
    )
    rows = fetch_all(
        config,
        """
        select book_id, enabled
        from source_set_books
        where source_set_id = ?
        order by book_id
        """,
        (source_sets.RULES_CORE_SOURCE_SET_ID,),
    )
    active = source_sets.get_active_source_set_id(config)
    enabled_by_book = {row["book_id"]: row["enabled"] for row in rows}

    assert summary.source_sets_created == 1
    assert summary.book_rows_inserted == 4
    assert summary.active_source_set_id == source_sets.RULES_CORE_SOURCE_SET_ID
    assert source_set["name"] == source_sets.RULES_CORE_SOURCE_SET_NAME
    assert source_set["is_builtin"] == 1
    assert len(rows) == 4
    assert enabled_by_book == {
        "career-compendium": 1,
        "core-rules": 1,
        "sigmars-heirs": 0,
        "thousand-thrones": 0,
    }
    assert active == source_sets.RULES_CORE_SOURCE_SET_ID


def test_builtin_source_set_sync_is_idempotent_and_preserves_toggles(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)

    source_sets.ensure_builtin_source_sets(config)
    source_sets.set_book_enabled(
        config,
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "core-rules",
        False,
    )
    second = source_sets.ensure_builtin_source_sets(config)

    row = fetch_one(
        config,
        """
        select enabled
        from source_set_books
        where source_set_id = ? and book_id = 'core-rules'
        """,
        (source_sets.RULES_CORE_SOURCE_SET_ID,),
    )
    assert second.source_sets_created == 0
    assert second.book_rows_inserted == 0
    assert row["enabled"] == 0


def test_sync_adds_missing_rows_for_new_books_without_changing_existing_toggles(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)
    source_sets.set_book_enabled(
        config,
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "core-rules",
        False,
    )

    with open_connection(config.db_path) as connection:
        insert_book(
            connection,
            book_id="new-toolkit",
            title="New Toolkit",
            category="Rules and Mechanics Toolkits",
        )
        connection.commit()

    summary = source_sets.ensure_builtin_source_sets(config)

    rows = fetch_all(
        config,
        """
        select book_id, enabled
        from source_set_books
        where source_set_id = ?
        order by book_id
        """,
        (source_sets.RULES_CORE_SOURCE_SET_ID,),
    )
    enabled_by_book = {row["book_id"]: row["enabled"] for row in rows}
    assert summary.book_rows_inserted == 1
    assert enabled_by_book["new-toolkit"] == 1
    assert enabled_by_book["core-rules"] == 0


def test_list_source_sets_and_books_include_readiness_state(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)

    listed_sets = source_sets.list_source_sets(config)
    listed_books = source_sets.list_source_set_books(
        config,
        source_sets.RULES_CORE_SOURCE_SET_ID,
    )

    assert listed_sets == (
        source_sets.SourceSet(
            id=source_sets.RULES_CORE_SOURCE_SET_ID,
            name=source_sets.RULES_CORE_SOURCE_SET_NAME,
            description=source_sets.RULES_CORE_SOURCE_SET_DESCRIPTION,
            is_builtin=True,
        ),
    )
    assert [book.book_id for book in listed_books] == [
        "thousand-thrones",
        "core-rules",
        "career-compendium",
        "sigmars-heirs",
    ]
    assert [book.enabled for book in listed_books] == [False, True, True, False]
    assert [book.search_ready for book in listed_books] == [False, True, True, True]


def test_active_source_set_and_enabled_book_ids(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)

    source_sets.set_book_enabled(
        config,
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "career-compendium",
        False,
    )

    assert source_sets.get_active_source_set_id(config) == source_sets.RULES_CORE_SOURCE_SET_ID
    source_sets.set_book_enabled(
        config,
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "thousand-thrones",
        True,
    )

    assert source_sets.enabled_book_ids(config) == (
        "core-rules",
        "thousand-thrones",
    )
    assert source_sets.enabled_book_ids(
        config,
        source_sets.RULES_CORE_SOURCE_SET_ID,
    ) == ("core-rules", "thousand-thrones")


def test_set_active_source_set_rejects_missing_set(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path):
        pass

    with pytest.raises(source_sets.SourceSetNotFoundError, match="missing-set"):
        source_sets.set_active_source_set(config, "missing-set")


def test_set_book_enabled_rejects_missing_source_set_and_book(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)

    with pytest.raises(source_sets.SourceSetNotFoundError, match="missing-set"):
        source_sets.set_book_enabled(config, "missing-set", "core-rules", True)

    with pytest.raises(source_sets.BookNotFoundError, match="missing-book"):
        source_sets.set_book_enabled(
            config,
            source_sets.RULES_CORE_SOURCE_SET_ID,
            "missing-book",
            True,
        )


def test_set_book_enabled_inserts_missing_relationship_with_default(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            delete from source_set_books
            where source_set_id = ? and book_id = 'sigmars-heirs'
            """,
            (source_sets.RULES_CORE_SOURCE_SET_ID,),
        )
        connection.commit()

    source_sets.set_book_enabled(
        config,
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "sigmars-heirs",
        True,
    )

    row = fetch_one(
        config,
        """
        select enabled
        from source_set_books
        where source_set_id = ? and book_id = 'sigmars-heirs'
        """,
        (source_sets.RULES_CORE_SOURCE_SET_ID,),
    )
    assert row["enabled"] == 1


def test_builtin_source_set_conflicts_reject_user_owned_or_wrong_name_rows(
    tmp_path: Path,
) -> None:
    user_owned = make_config(tmp_path / "user-owned")
    with initialize_database(user_owned.db_path) as connection:
        connection.execute(
            """
            insert into source_sets (id, name, is_builtin, created_at, updated_at)
            values ('rules-core', 'Rules/Core', 0, '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """
        )

    wrong_name = make_config(tmp_path / "wrong-name")
    with initialize_database(wrong_name.db_path) as connection:
        connection.execute(
            """
            insert into source_sets (id, name, is_builtin, created_at, updated_at)
            values ('rules-core', 'Different Name', 1, '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """
        )

    with pytest.raises(source_sets.SourceSetConflictError, match="user-owned"):
        source_sets.ensure_builtin_source_sets(user_owned)

    with pytest.raises(source_sets.SourceSetConflictError, match="Different Name"):
        source_sets.ensure_builtin_source_sets(wrong_name)


def test_builtin_source_set_conflict_rejects_rules_core_name_on_different_id(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into source_sets (id, name, is_builtin, created_at, updated_at)
            values ('custom-rules-core', 'Rules/Core', 0, '2026-06-04T00:00:00Z',
                    '2026-06-04T00:00:00Z')
            """
        )

    with pytest.raises(source_sets.SourceSetConflictError, match="custom-rules-core"):
        source_sets.ensure_builtin_source_sets(config)


def test_invalid_or_deleted_active_setting_returns_none(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)
    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update app_settings
            set value_json = '{not-json'
            where key = ?
            """,
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        )
        connection.commit()

    assert source_sets.get_active_source_set_id(config) is None

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update app_settings
            set value_json = '123'
            where key = ?
            """,
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        )
        connection.commit()

    assert source_sets.get_active_source_set_id(config) is None

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update app_settings
            set value_json = '"missing-set"'
            where key = ?
            """,
            (source_sets.ACTIVE_SOURCE_SET_SETTING_KEY,),
        )
        connection.commit()

    assert source_sets.get_active_source_set_id(config) is None


def test_enabled_book_ids_error_and_empty_enabled_set(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_books(config)
    source_sets.ensure_builtin_source_sets(config)

    with pytest.raises(source_sets.SourceSetNotFoundError, match="missing-set"):
        source_sets.enabled_book_ids(config, source_set_id="missing-set")

    with open_connection(config.db_path) as connection:
        connection.execute(
            """
            update source_set_books
            set enabled = 0
            where source_set_id = ?
            """,
            (source_sets.RULES_CORE_SOURCE_SET_ID,),
        )
        connection.commit()

    assert source_sets.enabled_book_ids(
        config,
        source_sets.RULES_CORE_SOURCE_SET_ID,
    ) == ()


def test_enabled_book_ids_requires_valid_active_source_set(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    with initialize_database(config.db_path):
        pass

    with pytest.raises(source_sets.ActiveSourceSetMissingError):
        source_sets.enabled_book_ids(config)


def test_default_enabled_for_source_set_rules(tmp_path: Path) -> None:
    assert source_sets.default_enabled_for_source_set(
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "Core Book & GM Essentials",
    )
    assert source_sets.default_enabled_for_source_set(
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "Rules and Mechanics Toolkits",
    )
    assert not source_sets.default_enabled_for_source_set(
        source_sets.RULES_CORE_SOURCE_SET_ID,
        "World Guides and Faction Sourcebooks",
    )
    assert not source_sets.default_enabled_for_source_set(
        "custom-set",
        "Rules and Mechanics Toolkits",
    )

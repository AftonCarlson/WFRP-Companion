from __future__ import annotations

import json
from pathlib import Path

from tests.assistant.test_retrieval import insert_searchable_page, make_config
from wfrp_companion.assistant.evidence_constraints import EvidenceConstraint
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.structured_evidence import resolver
from wfrp_companion.structured_evidence.store import structured_evidence_snapshot_sha256


def constraint(**overrides: object) -> EvidenceConstraint:
    values = {
        "requirement_id": "structured",
        "requirement_type": "topical_evidence",
        "canonical_subject": "advanced armour",
        "subject_terms": ("advanced", "armour"),
        "subject_aliases": (),
        "excluded_terms": (),
        "required_terms": (),
        "structural_terms": (),
        "object_type_hints": (),
        "structured_lookup_policy": "allowed",
    }
    values.update(overrides)
    return EvidenceConstraint(**values)  # type: ignore[arg-type]


def seed_validated_table(
    tmp_path: Path,
    *,
    second: bool = False,
    malformed_payload: bool = False,
) -> tuple[object, object]:
    config = make_config(tmp_path)
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=112,
            text="Synthetic structured evidence page.",
            page_label="112",
        )
        payload = {
            "schema_version": 1,
            "object_shape": "structured_table",
            "identity": {
                "title_normalized": "advanced armour",
                "table_number_normalized": "5-6",
            },
            "structure": {"columns": [], "rows": []},
        }
        insert_validated_row(
            connection,
            validated_id="validated-table",
            payload_json="{" if malformed_payload else json.dumps(payload),
            table_number_normalized="5-6",
            printed_page_end="112" if not malformed_payload else "113",
        )
        insert_alias(connection, validated_id="validated-table", alias="advanced armour")
        if second:
            insert_validated_row(
                connection,
                validated_id="validated-table-2",
                payload_json=json.dumps(payload),
                table_number_normalized="5-7",
            )
            insert_alias(
                connection,
                validated_id="validated-table-2",
                alias="advanced armour",
            )
    return config, connection


def insert_validated_row(
    connection,
    *,
    validated_id: str,
    payload_json: str,
    table_number_normalized: str | None,
    printed_page_end: str = "112",
    source_snapshot_sha256: str | None = None,
) -> None:
    source_snapshot = source_snapshot_sha256 or structured_evidence_snapshot_sha256(
        connection,
        "core-rules",
    )
    connection.execute(
        """
        insert into validated_structured_objects (
          id,
          book_id,
          primary_page_id,
          object_shape,
          content_kind,
          entity_kind,
          title,
          table_number,
          table_number_normalized,
          page_start,
          page_end,
          printed_page_start,
          printed_page_end,
          heading_path_json,
          payload_schema_version,
          payload_json,
          source_snapshot_sha256,
          validation_status,
          review_state,
          created_at,
          updated_at
        )
        values (?, 'core-rules', 'core-rules:112', 'structured_table',
                'equipment_table', 'rule', 'Advanced Armour', 'Table 5-6',
                ?, 112, 112, '112', ?, '["Chapter V"]', 1, ?,
                ?, 'active', 'human_approved',
                '2026-06-10T00:00:00Z', '2026-06-10T00:00:00Z')
        """,
        (
            validated_id,
            table_number_normalized,
            printed_page_end,
            payload_json,
            source_snapshot,
        ),
    )


def insert_alias(connection, *, validated_id: str, alias: str) -> None:
    connection.execute(
        """
        insert into validated_structured_object_aliases (
          validated_object_id,
          book_id,
          alias,
          alias_normalized,
          alias_source,
          confidence,
          created_at
        )
        values (?, 'core-rules', ?, ?, 'manual', 1, '2026-06-10T00:00:00Z')
        """,
        (validated_id, alias, alias),
    )


def fetch_row(tmp_path: Path):
    config, _ = seed_validated_table(tmp_path)
    connection = initialize_database(config.db_path)
    return connection, resolver.active_validated_rows(
        connection,
        book_ids=("core-rules",),
    )[0]


def test_resolver_reports_policy_and_scope_skip_reasons(tmp_path: Path) -> None:
    connection, _ = fetch_row(tmp_path)

    assert (
        resolver.resolve_validated_structured_candidates(
            connection,
            query="advanced armour",
            book_ids=("core-rules",),
            constraint=None,
            limit=1,
        ).skip_reason
        == "no_requirement_policy"
    )
    assert (
        resolver.resolve_validated_structured_candidates(
            connection,
            query="advanced armour",
            book_ids=(),
            constraint=constraint(),
            limit=1,
        ).skip_reason
        == "no_source_books"
    )
    assert (
        resolver.resolve_validated_structured_candidates(
            connection,
            query="advanced armour",
            book_ids=("core-rules",),
            constraint=constraint(),
            limit=0,
        ).skip_reason
        == "limit_zero"
    )
    assert resolver.active_validated_rows(connection, book_ids=()) == ()


def test_resolver_ignores_active_validated_row_after_source_snapshot_drift(
    tmp_path: Path,
) -> None:
    config, _ = seed_validated_table(tmp_path)
    with initialize_database(config.db_path) as connection:
        before = resolver.resolve_validated_structured_candidates(
            connection,
            query="advanced armour",
            book_ids=("core-rules",),
            constraint=constraint(),
            limit=1,
        )
        connection.execute(
            """
            update page_text
            set text_sha256 = 'changed-page-text-snapshot'
            where page_id = 'core-rules:112'
            """
        )
        active_rows = resolver.active_validated_rows(
            connection,
            book_ids=("core-rules",),
        )
        after = resolver.resolve_validated_structured_candidates(
            connection,
            query="advanced armour",
            book_ids=("core-rules",),
            constraint=constraint(),
            limit=1,
        )

    assert len(before.candidates) == 1
    assert active_rows == ()
    assert after.candidates == ()
    assert after.skip_reason == "no_active_match"


def test_resolver_filters_constraint_mismatches(tmp_path: Path) -> None:
    connection, _ = fetch_row(tmp_path)
    mismatches = (
        constraint(structured_object_shape_hints=("profile_bundle",)),
        constraint(structured_content_kind_hints=("combat_table",)),
        constraint(structured_entity_kind_hints=("monster",)),
        constraint(table_number_hints=("9-9",)),
        constraint(book_title_hints=("old world bestiary",)),
        constraint(page_hints=("999",)),
    )

    for item in mismatches:
        result = resolver.resolve_validated_structured_candidates(
            connection,
            query="advanced armour",
            book_ids=("core-rules",),
            constraint=item,
            limit=1,
        )
        assert result.candidates == ()
        assert result.skip_reason == "no_active_match"
    result = resolver.resolve_validated_structured_candidates(
        connection,
        query="unrelated monster",
        book_ids=("core-rules",),
        constraint=constraint(canonical_subject=None, subject_terms=()),
        limit=1,
    )
    assert result.candidates == ()
    assert result.skip_reason == "no_active_match"


def test_resolver_matches_table_number_terms_and_respects_limit(
    tmp_path: Path,
) -> None:
    config, _ = seed_validated_table(tmp_path, second=True)
    with initialize_database(config.db_path) as connection:
        result = resolver.resolve_validated_structured_candidates(
            connection,
            query="table 5-6",
            book_ids=("core-rules",),
            constraint=constraint(table_number_hints=("5-6",)),
            limit=1,
        )
        row = resolver.active_validated_rows(connection, book_ids=("core-rules",))[0]

    assert len(result.candidates) == 1
    assert result.candidates[0].validated_structured_object_id == "validated-table"
    assert resolver.row_matches_query(row, (), "table 5-6", constraint())
    assert resolver.row_matches_query(row, (), "advanced equipment", constraint())
    assert not resolver.row_matches_query(
        row,
        (),
        "",
        constraint(canonical_subject=None, subject_terms=()),
    )
    assert not resolver.row_matches_query(
        row,
        (),
        "the",
        constraint(canonical_subject=None, subject_terms=()),
    )


def test_resolver_defensive_helpers_handle_invalid_payloads_and_json(
    tmp_path: Path,
) -> None:
    config, _ = seed_validated_table(tmp_path, malformed_payload=True)
    with initialize_database(config.db_path) as connection:
        row = resolver.active_validated_rows(connection, book_ids=("core-rules",))[0]
        candidate = resolver.candidate_from_validated_row(
            connection,
            row,
            aliases=(),
            policy="allowed",
            base_score=-1,
        )
        connection.execute(
            """
            update validated_structured_objects
            set table_number_normalized = '5 6'
            where id = 'validated-table'
            """
        )
        alias_row = resolver.active_validated_rows(
            connection,
            book_ids=("core-rules",),
        )[0]

    assert candidate.validated_payload_hash
    assert resolver.row_matches_table_hints(alias_row, (), ("5-6",))
    assert not resolver.row_matches_table_hints(row, (), ("9-9",))
    assert resolver.structured_relevance_terms("other") == "structured evidence"
    assert resolver.normalized_shape_hint("strange shape") is None
    assert not resolver.phrase_contains("", "advanced")
    assert resolver.payload_from_row(row) == {}
    assert resolver.json_string_list(None) == ()
    assert resolver.json_string_list("{") == ()
    assert resolver.json_string_list("{}") == ()

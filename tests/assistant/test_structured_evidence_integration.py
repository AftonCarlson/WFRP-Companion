from __future__ import annotations

import json
from pathlib import Path

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import context_resolution
from wfrp_companion.assistant import evidence_constraints
from wfrp_companion.assistant import evidence_validation
from wfrp_companion.assistant import requirement_planner
from wfrp_companion.assistant import retrieval
from wfrp_companion.assistant import turn_contract
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import source_sets
from tests.assistant.test_retrieval import (
    insert_searchable_page,
    make_config,
)


def insert_validated_table(config) -> None:  # noqa: ANN001
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="core-rules",
            title="Core Rules",
            category="Core Book & GM Essentials",
            page_number=112,
            text="Armour rules mention hit locations.",
            page_label="112",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'core-rules'"
        )
        payload = {
            "schema_version": 1,
            "object_shape": "structured_table",
            "identity": {
                "table_number_raw": "Table 5-6",
                "table_number_normalized": "5-6",
                "title_raw": "Advanced Armour",
                "title_normalized": "advanced armour",
                "aliases": ["table 5-6", "armour points by location"],
            },
            "structure": {
                "columns": [{"key": "location", "label_raw": "Location"}],
                "rows": [
                    {
                        "ordinal": 1,
                        "range_raw": None,
                        "cells": {"location": "Head", "ap": "1"},
                        "raw_text": "Head 1",
                        "confidence": 1,
                        "suspicious_cells": [],
                    }
                ],
            },
        }
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
              payload_schema_version,
              payload_json,
              source_snapshot_sha256,
              validation_status,
              review_state,
              created_at,
              updated_at,
              reviewed_at
            )
            values (
              'validated-table',
              'core-rules',
              'core-rules:112',
              'structured_table',
              'equipment_table',
              'none',
              'Advanced Armour',
              'Table 5-6',
              '5-6',
              112,
              112,
              '112',
              '112',
              1,
              ?,
              'structured-snapshot',
              'active',
              'human_approved',
              '2026-06-10T00:00:00Z',
              '2026-06-10T00:00:00Z',
              '2026-06-10T00:00:00Z'
            )
            """,
            (json.dumps(payload),),
        )
        for alias in ("table 5-6", "armour points by location", "advanced armour"):
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
                values (
                  'validated-table',
                  'core-rules',
                  ?,
                  ?,
                  'manual',
                  1,
                  '2026-06-10T00:00:00Z'
                )
                """,
                (alias, alias.replace("-", " ").lower()),
            )
    source_sets.ensure_builtin_source_sets(config)


def insert_validated_profile(config) -> None:  # noqa: ANN001
    with initialize_database(config.db_path) as connection:
        insert_searchable_page(
            connection,
            book_id="bestiary",
            title="Old World Bestiary",
            category="Rules and Mechanics Toolkits",
            page_number=104,
            text="Common Orc profile overview.",
            page_label="104",
        )
        connection.execute(
            "update books set search_status = 'indexed' where id = 'bestiary'"
        )
        payload = {
            "schema_version": 1,
            "object_shape": "profile_bundle",
            "identity": {
                "name_raw": "Common Orc",
                "name_normalized": "common orc",
                "aliases": ["orc", "orcs", "common orc"],
            },
            "source": {
                "book_id": "bestiary",
                "page_start": 104,
                "page_end": 104,
                "text_snapshot_sha256": "profile-snapshot",
            },
            "profile": {
                "description": "Synthetic reviewed profile.",
                "main_profile": {"ws": "35", "bs": "35"},
                "secondary_profile": {"a": "1", "w": "12"},
                "skills": ["Perception"],
                "talents": ["Strike Mighty Blow"],
                "traits": ["Animosity"],
                "special_rules": ["Synthetic reviewed rule"],
                "weapons": ["Choppa"],
                "armour": ["Light Armour"],
                "trappings": ["Shield"],
                "notes": ["Validated synthetic profile"],
            },
            "provenance": {"field_confidence": {"main_profile": 1}},
        }
        connection.execute(
            """
            insert into validated_structured_objects (
              id,
              book_id,
              primary_page_id,
              object_shape,
              content_kind,
              entity_kind,
              canonical_name,
              title,
              page_start,
              page_end,
              printed_page_start,
              printed_page_end,
              payload_schema_version,
              payload_json,
              source_snapshot_sha256,
              validation_status,
              review_state,
              created_at,
              updated_at,
              reviewed_at
            )
            values (
              'validated-profile',
              'bestiary',
              'bestiary:104',
              'profile_bundle',
              'creature_profile',
              'monster',
              'Common Orc',
              'Common Orc',
              104,
              104,
              '104',
              '104',
              1,
              ?,
              'profile-snapshot',
              'active',
              'human_approved',
              '2026-06-10T00:00:00Z',
              '2026-06-10T00:00:00Z',
              '2026-06-10T00:00:00Z'
            )
            """,
            (json.dumps(payload),),
        )
        for alias in ("orc", "orcs", "common orc"):
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
                values (
                  'validated-profile',
                  'bestiary',
                  ?,
                  ?,
                  'manual',
                  1,
                  '2026-06-10T00:00:00Z'
                )
                """,
                (alias, alias.lower()),
            )
    source_sets.ensure_builtin_source_sets(config)


def decision(kind: turn_contract.TurnKind, subject: str | None) -> turn_contract.TurnDecision:
    return turn_contract.TurnDecision(
        turn_kind=kind,
        answer_mode="research",
        subject=subject,
        confidence="medium",
        reasons=(f"{kind}_test",),
        reader_context_policy="routing_hint",
    )


def resolved(
    *,
    raw_query: str,
    intent: str,
    subject: str | None,
) -> context_resolution.ResolvedResearchRequest:
    return context_resolution.ResolvedResearchRequest(
        raw_query=raw_query,
        resolved_query=raw_query,
        intent=intent,
        subject=subject,
        page_reference=None,
        active_book_id=None,
        used_active_subject=False,
    )


def test_requirement_planner_persists_structured_lookup_policy() -> None:
    statline_specs = requirement_planner.plan_requirements(
        "give me orc stats",
        decision=decision("statline_lookup", "orc"),
        resolved=resolved(
            raw_query="give me orc stats",
            intent="statline_lookup",
            subject="orc",
        ),
    )
    lore_specs = requirement_planner.plan_requirements(
        "tell me about orcs",
        decision=decision("lore_lookup", "orcs"),
        resolved=resolved(
            raw_query="tell me about orcs",
            intent="lore_lookup",
            subject="orcs",
        ),
    )

    statline_requirement = requirement_planner.requirement_contract.to_evidence_requirement(
        statline_specs[0]
    )
    lore_requirement = requirement_planner.requirement_contract.to_evidence_requirement(
        lore_specs[0]
    )
    action = requirement_planner.planned_action_for_spec(statline_specs[0])

    assert statline_requirement.structured_lookup_policy == "required"
    assert statline_requirement.structured_object_shape_hints == ("profile_bundle",)
    assert action.arguments["structured_lookup_policy"] == "required"
    assert action.arguments["structured_object_shape_hints"] == ["profile_bundle"]
    assert lore_requirement.structured_lookup_policy == "not_primary"


def test_retrieval_uses_active_validated_table_only_when_policy_allows(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_validated_table(config)
    thread = chat_store.create_thread(config)
    requirement = agent_planning.EvidenceRequirement(
        id="armor_table",
        requirement_type="topical_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="armour points by location",
            surface="armour points by location",
            include_terms=("armour points by location",),
        ),
        structured_lookup_policy="allowed",
        structured_object_shape_hints=("structured_table",),
        table_number_hints=("5-6",),
    )

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "table 5-6 armour points by location",
        hit_limit=3,
        total_char_limit=1200,
        window_chars=400,
        requirement_constraint=evidence_constraints.constraint_from_requirement(
            requirement
        ),
    )

    assert context.diagnostics is not None
    assert context.diagnostics.channel_counts["validated_structured"] == 1
    assert context.hits[0].validated_structured_object_id == "validated-table"
    assert context.hits[0].structured_lookup_policy == "allowed"
    assert context.hits[0].validated_validation_status == "active"
    assert "validated_structured" in " ".join(context.hits[0].rank_reasons)


def test_retrieval_skips_structured_lookup_for_not_primary_policy(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_validated_table(config)
    thread = chat_store.create_thread(config)
    requirement = agent_planning.EvidenceRequirement(
        id="about_orcs",
        requirement_type="topical_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="orcs",
            surface="orcs",
            include_terms=("orcs",),
        ),
        structured_lookup_policy="not_primary",
    )

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "tell me about orcs",
        hit_limit=3,
        total_char_limit=1200,
        window_chars=400,
        requirement_constraint=evidence_constraints.constraint_from_requirement(
            requirement
        ),
    )

    assert context.diagnostics is not None
    assert context.diagnostics.channel_counts["validated_structured"] == 0
    assert (
        context.diagnostics.channel_skip_reasons["validated_structured"]
        == "policy_not_primary"
    )
    assert all(hit.validated_structured_object_id is None for hit in context.hits)


def test_retrieval_ignores_stale_validated_structured_objects(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_validated_table(config)
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            update validated_structured_objects
            set validation_status = 'stale'
            where id = 'validated-table'
            """
        )
    thread = chat_store.create_thread(config)
    requirement = agent_planning.EvidenceRequirement(
        id="armor_table",
        requirement_type="topical_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="armour points by location",
            surface="armour points by location",
            include_terms=("armour points by location",),
        ),
        structured_lookup_policy="allowed",
        structured_object_shape_hints=("structured_table",),
        table_number_hints=("5-6",),
    )

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "table 5-6 armour points by location",
        hit_limit=3,
        total_char_limit=1200,
        window_chars=400,
        requirement_constraint=evidence_constraints.constraint_from_requirement(
            requirement
        ),
    )

    assert context.diagnostics is not None
    assert context.diagnostics.channel_counts["validated_structured"] == 0
    assert (
        context.diagnostics.channel_skip_reasons["validated_structured"]
        == "no_active_match"
    )
    assert all(hit.validated_structured_object_id is None for hit in context.hits)


def test_retrieval_resolves_active_validated_profile_for_statline_policy(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_validated_profile(config)
    thread = chat_store.create_thread(config)
    requirement = agent_planning.EvidenceRequirement(
        id="statline_orc",
        requirement_type="statline_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="orc",
            surface="orc",
            include_terms=("orc", "profile", "statline"),
        ),
        structured_lookup_policy="required",
        structured_object_shape_hints=("profile_bundle",),
        structured_entity_kind_hints=("monster", "npc", "creature"),
    )

    context = retrieval.retrieve_context(
        config,
        thread.id,
        "give me orc stats",
        hit_limit=3,
        total_char_limit=1200,
        window_chars=400,
        requirement_constraint=evidence_constraints.constraint_from_requirement(
            requirement
        ),
    )

    assert context.diagnostics is not None
    assert context.diagnostics.channel_counts["validated_structured"] == 1
    assert context.hits[0].validated_structured_object_id == "validated-profile"
    assert context.hits[0].object_type == "validated_profile_bundle"
    assert context.hits[0].structured_lookup_policy == "required"


def test_validation_accepts_validated_structured_hit_under_allowed_policy() -> None:
    requirement = agent_planning.EvidenceRequirement(
        id="armor_table",
        requirement_type="topical_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="armour points by location",
            surface="armour points by location",
            include_terms=("armour points by location",),
        ),
        structured_lookup_policy="allowed",
        structured_object_shape_hints=("structured_table",),
    )
    hit = retrieval.RetrievedHit(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:112",
        page_number=112,
        pdf_page_number=112,
        page_label="112",
        snippet="Advanced Armour",
        score=-10,
        rank=1,
        context_text="Advanced Armour table 5-6 armour points by location",
        object_type="validated_structured_table",
        object_title="Advanced Armour",
        validated_structured_object_id="validated-table",
        validated_payload_schema_version=1,
        validated_payload_hash="payload-hash",
        validated_validation_status="active",
        validated_source_snapshot_sha256="structured-snapshot",
        structured_lookup_policy="allowed",
    )

    accepted = evidence_validation.validate_hits_for_requirement(
        (hit,),
        requirement=requirement,
        source_book_ids=("core-rules",),
    )
    rejected = evidence_validation.validate_hits_for_requirement(
        (hit,),
        requirement=agent_planning.EvidenceRequirement(
            id="about_orcs",
            requirement_type="topical_evidence",
            subject=agent_planning.SubjectConstraint(
                canonical="orcs",
                surface="orcs",
                include_terms=("orcs",),
            ),
            structured_lookup_policy="not_primary",
        ),
        source_book_ids=("core-rules",),
    )

    assert accepted.status == "sufficient"
    assert accepted.judgments[0].reason_code == "validated_structured_evidence"
    assert rejected.status == "insufficient"
    assert rejected.judgments[0].reason_code == "structured_lookup_not_allowed"


def test_validation_rejects_unvalidated_structured_hit() -> None:
    requirement = agent_planning.EvidenceRequirement(
        id="armor_table",
        requirement_type="topical_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="armour points by location",
            surface="armour points by location",
            include_terms=("armour points by location",),
        ),
        structured_lookup_policy="allowed",
        structured_object_shape_hints=("structured_table",),
    )
    hit = retrieval.RetrievedHit(
        book_id="core-rules",
        title="Core Rules",
        category="Core",
        page_id="core-rules:112",
        page_number=112,
        pdf_page_number=112,
        page_label="112",
        snippet="Advanced Armour",
        score=-10,
        rank=1,
        context_text="Advanced Armour table 5-6 armour points by location",
        object_type="validated_structured_table",
        object_title="Advanced Armour",
        structured_lookup_policy="allowed",
    )

    result = evidence_validation.validate_hits_for_requirement(
        (hit,),
        requirement=requirement,
        source_book_ids=("core-rules",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "unvalidated_structured_evidence"


def test_retrieval_run_persists_validated_structured_hit_metadata(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    insert_validated_table(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="table 5-6 armour points by location",
        idempotency_key="structured-metadata",
        provider="openai",
        model="gpt-5.4-mini",
    )
    requirement = agent_planning.EvidenceRequirement(
        id="armor_table",
        requirement_type="topical_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="armour points by location",
            surface="armour points by location",
            include_terms=("armour points by location",),
        ),
        structured_lookup_policy="allowed",
        structured_object_shape_hints=("structured_table",),
        table_number_hints=("5-6",),
    )
    context = retrieval.retrieve_context(
        config,
        thread.id,
        "table 5-6 armour points by location",
        hit_limit=3,
        total_char_limit=1200,
        window_chars=400,
        requirement_constraint=evidence_constraints.constraint_from_requirement(
            requirement
        ),
    )

    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="table 5-6 armour points by location",
        hits=context.hits,
        source_book_ids=context.source_book_ids,
        diagnostics=context.diagnostics,
    )

    with initialize_database(config.db_path) as connection:
        metadata = json.loads(
            connection.execute(
                """
                select metadata_json
                from retrieval_hits
                where retrieval_run_id = ?
                order by rank
                limit 1
                """,
                (retrieval_run_id,),
            ).fetchone()["metadata_json"]
        )

    assert metadata["validated_structured_object_id"] == "validated-table"
    assert metadata["validated_payload_schema_version"] == 1
    assert metadata["validated_payload_hash"]
    assert metadata["validated_validation_status"] == "active"
    assert metadata["validated_source_snapshot_sha256"] == "structured-snapshot"
    assert metadata["structured_lookup_policy"] == "allowed"

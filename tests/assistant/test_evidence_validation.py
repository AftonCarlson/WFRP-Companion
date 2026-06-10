from __future__ import annotations

from pathlib import Path

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import chat_store
from wfrp_companion.assistant import evidence_constraints
from wfrp_companion.assistant import evidence_validation
from wfrp_companion.assistant import statline_fields
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.library import source_sets


def make_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        pdf_root=tmp_path / "pdf-root",
        data_dir=data_dir,
        db_path=data_dir / "wfrp_companion.sqlite",
        asset_dir=data_dir / "library" / "assets",
    )


def seed_book(config: AppConfig) -> None:
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
            values ('bestiary', 'core', 'Old World Bestiary',
                    'Rules and Mechanics Toolkits', 'bestiary.pdf',
                    '/source/bestiary.pdf', '/managed/bestiary.pdf',
                    'source-sha', 'managed-sha', 150, 'copied', 'imported',
                    'indexed', 'not_scanned', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """
        )
        connection.execute(
            """
            insert into pages (
              id,
              book_id,
              page_number,
              page_label,
              extraction_method,
              embedded_text_chars,
              text_chars,
              word_count,
              image_count,
              ocr_attempted,
              has_text
            )
            values ('bestiary:101', 'bestiary', 101, '99', 'ocr',
                    0, 20, 4, 0, 1, 1)
            """
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
            values ('harpy-stat', 'bestiary', 'bestiary:101', 'stat_block',
                    null, 'Harpy', '["Creatures", "Harpy"]', 101, 101,
                    null, null, null, 'Harpy stat_block: M 4 WS 31.',
                    'Harpy stat_block: M 4 WS 31.', '{}', 0.95,
                    'synthetic', 'sha-harpy-stat', '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """
        )
    source_sets.ensure_builtin_source_sets(config)


def hit(
    *,
    book_id: str = "bestiary",
    title: str = "Old World Bestiary",
    context_text: str,
    object_type: str = "stat_block",
    object_title: str | None = "Harpy",
    source_object_id: str | None = "harpy-stat",
    rank_reasons: tuple[str, ...] = (),
) -> RetrievedHit:
    return RetrievedHit(
        book_id=book_id,
        title=title,
        category="Rules and Mechanics Toolkits",
        page_id=f"{book_id}:101",
        page_number=101,
        pdf_page_number=101,
        page_label="99",
        snippet=context_text,
        score=1.0,
        rank=1,
        context_text=context_text,
        source_object_id=source_object_id,
        object_type=object_type,
        object_title=object_title,
        page_start=101,
        page_end=101,
        page_range_label="99",
        rank_reasons=rank_reasons,
    )


def subject_constraint(
    *,
    canonical: str | None,
    include_terms: tuple[str, ...] = (),
    exclude_terms: tuple[str, ...] = (),
) -> agent_planning.SubjectConstraint:
    return agent_planning.SubjectConstraint(
        canonical=canonical,
        surface=canonical,
        include_terms=include_terms,
        exclude_terms=exclude_terms,
    )


def requirement(
    *,
    requirement_type: agent_planning.RequirementType,
    subject: agent_planning.SubjectConstraint,
    required_terms: tuple[str, ...] = (),
    excluded_terms: tuple[str, ...] = (),
    object_type_hints: tuple[str, ...] = (),
) -> agent_planning.EvidenceRequirement:
    return agent_planning.EvidenceRequirement(
        id="evidence_requirement",
        requirement_type=requirement_type,
        subject=subject,
        required_terms=required_terms,
        excluded_terms=excluded_terms,
        object_type_hints=object_type_hints,
        min_accepted_hits=1,
        required=True,
    )


def create_research_run(config: AppConfig) -> tuple[str, str, str, str, str]:
    seed_book(config)
    thread = chat_store.create_thread(config)
    queued = chat_store.create_queued_turn(
        config,
        thread.id,
        content="harpy statline",
        idempotency_key="send-1",
        provider="openai",
        model="gpt-5.4-mini",
    )
    research_run = chat_store.create_familiar_research_run(
        config,
        model_run_id=queued.model_run.id,
        raw_query="harpy statline",
        resolved_query="harpy statline",
        intent="statline_lookup",
        max_tool_rounds=4,
    )
    retrieval_run_id = chat_store.record_retrieval_run(
        config,
        thread_id=thread.id,
        message_id=queued.user_message.id,
        source_set_id=thread.active_source_set_id,
        query="harpy statline",
        hits=(),
        source_book_ids=("bestiary",),
    )
    return (
        thread.id,
        queued.user_message.id,
        queued.model_run.id,
        research_run.id,
        retrieval_run_id,
    )


def insert_source_object(
    config: AppConfig,
    *,
    object_id: str,
    book_id: str,
    page_id: str,
    object_type: str,
    title: str,
    text: str,
    parent_object_id: str | None = None,
) -> None:
    with initialize_database(config.db_path) as connection:
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
            values (?, ?, ?, ?, ?, ?, '[]', 101, 101, null, null, null,
                    ?, ?, '{}', 0.95, 'synthetic', ?, '2026-06-09T00:00:00Z',
                    '2026-06-09T00:00:00Z')
            """,
            (
                object_id,
                book_id,
                page_id,
                object_type,
                parent_object_id,
                title,
                text,
                text,
                f"sha-{object_id}",
            ),
        )


def insert_source_object_link(
    config: AppConfig,
    *,
    link_id: str,
    from_object_id: str,
    to_object_id: str,
    link_type: str,
) -> None:
    with initialize_database(config.db_path) as connection:
        connection.execute(
            """
            insert into source_object_links (
              id,
              from_object_id,
              to_object_id,
              link_type,
              label,
              confidence,
              evidence_json,
              created_at
            )
            values (?, ?, ?, ?, null, 0.95, '{}', '2026-06-09T00:00:00Z')
            """,
            (link_id, from_object_id, to_object_id, link_type),
        )


def test_validate_statline_requires_subject_source_and_stat_evidence() -> None:
    accepted = hit(context_text="Harpy stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10.")
    wrong_subject = hit(context_text="Gor stat_block: M 4 WS 33.", object_title="Gor")
    non_stat = hit(
        context_text="Harpy flying movement rules discuss altitude.",
        object_type="rule_section",
        object_title="Harpy",
        source_object_id="harpy-flight",
    )
    unchecked = hit(
        book_id="unchecked",
        title="Unchecked Book",
        context_text="Harpy stat_block: M 4 WS 31.",
    )

    result = evidence_validation.validate_hits(
        (accepted, wrong_subject, non_stat, unchecked),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert [judgment.status for judgment in result.judgments] == [
        "accepted",
        "rejected",
        "rejected",
        "rejected",
    ]
    assert [judgment.reason_code for judgment in result.judgments] == [
        "statline_evidence",
        "subject_mismatch",
        "missing_statline_markers",
        "unchecked_source",
    ]
    assert result.accepted_hits == (accepted,)


def test_validate_partial_page_and_topical_evidence_paths() -> None:
    partial_page = hit(
        context_text="Harpy creature entry mentions wings and claws.",
        object_type="page_fallback",
        object_title=None,
        source_object_id=None,
    )
    stat_text_page = hit(
        context_text="Harpy stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10.",
        object_type="page_fallback",
        object_title=None,
        source_object_id=None,
    )
    topical = hit(
        context_text="Harpy creature entry mentions wings and claws.",
        object_type="rule_section",
        object_title="Harpy",
        source_object_id="harpy-lore",
    )

    partial_result = evidence_validation.validate_hits(
        (partial_page,),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )
    stat_text_result = evidence_validation.validate_hits(
        (stat_text_page,),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )
    topical_result = evidence_validation.validate_hits(
        (topical,),
        subject="",
        intent="rules_lookup",
        source_book_ids=("bestiary",),
    )

    assert partial_result.status == "partial"
    assert partial_result.judgments[0].reason_code == "subject_only_page"
    assert stat_text_result.status == "sufficient"
    assert stat_text_result.judgments[0].reason_code == "statline_evidence"
    assert topical_result.status == "sufficient"
    assert topical_result.judgments[0].reason_code == "topical_evidence"
    assert evidence_validation.hit_mentions_subject(topical, "the") is True


def test_validate_requirement_rejects_excluded_subject_match() -> None:
    regular_ogre = hit(
        context_text="Ogre stat_block: M 6 WS 33 BS 20 S 45 T 42 W 15.",
        object_title="Ogre",
    )
    rat_ogre = hit(
        context_text="Rat Ogre stat_block: M 6 WS 33 BS 20 S 45 T 42 W 15.",
        object_title="Rat Ogre",
    )
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(
            canonical="ogre",
            include_terms=("ogre", "ogres"),
            exclude_terms=("rat ogre", "rat ogres"),
        ),
        required_terms=("ogre",),
        excluded_terms=("rat ogre", "rat ogres"),
        object_type_hints=("stat_block",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (regular_ogre, rat_ogre),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert [judgment.status for judgment in result.judgments] == [
        "accepted",
        "rejected",
    ]
    assert [judgment.reason_code for judgment in result.judgments] == [
        "statline_evidence",
        "excluded_subject",
    ]
    assert result.accepted_hits == (regular_ogre,)


def test_validate_requirement_accepts_broad_recommendation_evidence() -> None:
    karak_azgal = hit(
        title="Karak Azgal",
        context_text="Karak Azgal has mines, tombs, and underground adventure sites.",
        object_type="rule_section",
        object_title="Using Karak Azgal",
        source_object_id="karak-azgal-sites",
    )
    evidence_requirement = requirement(
        requirement_type="topical_evidence",
        subject=subject_constraint(canonical=None),
        required_terms=("underground", "adventure"),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (karak_azgal,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].status == "accepted"
    assert result.judgments[0].reason_code == "topical_evidence"


def test_constraint_normalization_splits_identity_structural_and_stat_terms() -> None:
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(
            canonical="Orc profile",
            include_terms=("Orc", "profile", "WS"),
            exclude_terms=("Rat Ogre",),
        ),
        required_terms=("Orc", "WS", "BS", "statistics"),
        excluded_terms=("Rat Ogre",),
        object_type_hints=("stat_block",),
    )

    constraint = evidence_constraints.constraint_from_requirement(evidence_requirement)

    assert constraint.canonical_subject == "Orc profile"
    assert constraint.subject_terms == ("orc",)
    assert constraint.structural_terms == (
        "profile",
        "ws",
        "bs",
        "statistics",
        "stat",
        "block",
    )
    assert constraint.required_terms == ()
    assert constraint.excluded_terms == ("rat ogre",)
    assert constraint.object_type_hints == ("stat_block",)


def test_named_statline_rejects_generic_profile_without_subject_anchor() -> None:
    ambassador = hit(
        title="Career Compendium",
        object_type="npc_profile",
        object_title="Ambassador",
        context_text=(
            "Ambassador profile WS 35 BS 35 S 35 T 35 "
            "Ag 30 Int 40 WP 40 Fel 50."
        ),
    )
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(
            canonical="orc",
            include_terms=("orc", "profile"),
            exclude_terms=(),
        ),
        required_terms=("orc", "WS", "BS", "S", "T", "Ag", "Int", "WP", "Fel"),
        object_type_hints=("stat_block", "monster_profile", "npc_profile"),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (ambassador,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].status == "rejected"
    assert result.judgments[0].reason_code == "subject_mismatch"


def test_generic_only_structural_subject_fails_closed() -> None:
    profile_hit = hit(
        object_type="npc_profile",
        object_title="Ambassador",
        context_text="Ambassador profile WS 35 BS 35 S 35 T 35.",
    )
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="profile", include_terms=("profile",)),
        required_terms=("profile", "WS", "BS"),
        object_type_hints=("npc_profile",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (profile_hit,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "generic_subject_only"


def test_null_canonical_structural_subject_fails_when_only_generic_terms_remain() -> None:
    profile_hit = hit(
        object_type="npc_profile",
        object_title="Ambassador",
        context_text="Ambassador profile WS 35 BS 35 S 35 T 35 W 10 M 4.",
    )
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical=None, include_terms=("profile",)),
        required_terms=("profile", "WS", "BS"),
        object_type_hints=("npc_profile",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (profile_hit,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "generic_subject_only"


def test_broad_topical_requirement_ignores_structural_include_terms() -> None:
    karak_azgal = hit(
        title="Karak Azgal",
        context_text="Karak Azgal has mines, tombs, and underground adventure sites.",
        object_type="rule_section",
        object_title="Using Karak Azgal",
        source_object_id="karak-azgal-sites",
    )
    evidence_requirement = requirement(
        requirement_type="topical_evidence",
        subject=subject_constraint(canonical=None, include_terms=("profile",)),
        required_terms=("underground", "adventure"),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (karak_azgal,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].status == "accepted"


def test_empty_canonical_subject_does_not_create_fake_subject_constraint() -> None:
    evidence_requirement = requirement(
        requirement_type="topical_evidence",
        subject=subject_constraint(canonical="", include_terms=("profile",)),
        required_terms=("underground",),
    )

    constraint = evidence_constraints.constraint_from_requirement(evidence_requirement)

    assert constraint.canonical_subject is None
    assert constraint.subject_terms == ()
    assert constraint.structural_terms == ("profile",)


def test_required_stat_terms_use_token_boundaries() -> None:
    assert evidence_validation.text_matches_required_term(
        "Harpy is strong and agile.",
        "S",
    ) is False
    assert evidence_validation.text_matches_required_term(
        "Harpy S 31.",
        "S",
    ) is True


def test_statline_field_parser_requires_token_boundaries() -> None:
    assert statline_fields.extract_stat_fields("Harpy is strong and agile.") == ()
    assert statline_fields.extract_stat_fields("Harpy S 31 T 30 WS 35.") == (
        "WS",
        "S",
        "T",
    )


def test_statline_object_type_alone_is_not_sufficient() -> None:
    profile_hit = hit(
        object_type="npc_profile",
        object_title="Harpy",
        context_text="Harpy profile describes wings, claws, and temperament.",
    )
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="harpy", include_terms=("harpy",)),
        required_terms=("harpy",),
        object_type_hints=("npc_profile",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (profile_hit,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "missing_statline_fields"


def test_fragmentary_statline_fields_are_not_sufficient() -> None:
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="Harpy", include_terms=("Harpy",)),
        object_type_hints=("stat_block",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="Harpy profile M 4 WS 35 BS 0.",
                object_type="stat_block",
                object_title="Harpy",
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "missing_statline_fields"


def test_statline_accepts_complete_profile_fields() -> None:
    profile_hit = hit(
        object_type="npc_profile",
        object_title="Harpy",
        context_text=(
            "Harpy profile M 4 WS 35 BS 0 S 31 T 30 "
            "Ag 42 Int 18 WP 25 Fel 10 A 2 W 11 SB 3 TB 3."
        ),
    )
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="harpy", include_terms=("harpy",)),
        required_terms=("harpy",),
        object_type_hints=("npc_profile",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (profile_hit,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].status == "accepted"


def test_object_type_hints_are_validation_constraints() -> None:
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="Harpy", include_terms=("Harpy",)),
        object_type_hints=("stat_block",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="Harpy profile M 4 WS 35 BS 0 S 31 T 30 W 10.",
                object_type="rule_section",
                object_title="Harpy",
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "object_type_mismatch"


def test_object_type_hint_matching_accepts_common_wording() -> None:
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="Harpy", include_terms=("Harpy",)),
        object_type_hints=("stat block",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="Harpy profile M 4 WS 35 BS 0 S 31 T 30 W 10.",
                object_type="stat_block",
                object_title="Harpy",
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].reason_code == "statline_evidence"


def test_object_type_hint_matching_normalizes_linked_rank_reasons() -> None:
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="Harpy", include_terms=("Harpy",)),
        object_type_hints=("stat block",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="Harpy profile M 4 WS 35 BS 0 S 31 T 30 W 10.",
                object_type="npc_profile",
                object_title="Harpy",
                rank_reasons=("linked_source_object:stat_block",),
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].reason_code == "statline_evidence"


def test_blank_object_type_hints_are_ignored() -> None:
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="Harpy", include_terms=("Harpy",)),
        object_type_hints=("   ",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="Harpy profile M 4 WS 35 BS 0 S 31 T 30 W 10.",
                object_type="stat_block",
                object_title="Harpy",
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].reason_code == "statline_evidence"


def test_unrelated_rank_reason_has_no_linked_object_type() -> None:
    assert (
        evidence_validation.normalized_linked_object_type_reason("fusion:rrf=0.02")
        is None
    )


def test_book_and_page_hint_matching_accepts_common_hint_wording() -> None:
    evidence_requirement = agent_planning.EvidenceRequirement(
        id="harpy_stats",
        requirement_type="statline_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical="Harpy",
            surface="Harpy",
            include_terms=("Harpy",),
            book_title_hints=("Old World Bestiary.pdf",),
            page_hints=("printed page 99",),
        ),
        object_type_hints=("stat_block",),
        min_accepted_hits=1,
        required=True,
    )

    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="Harpy profile M 4 WS 35 BS 0 S 31 T 30 W 10.",
                object_type="stat_block",
                object_title="Harpy",
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].reason_code == "statline_evidence"


def test_subjectless_page_evidence_can_use_book_and_page_hints() -> None:
    evidence_requirement = agent_planning.EvidenceRequirement(
        id="page_lookup",
        requirement_type="page_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical=None,
            surface=None,
            include_terms=("page",),
            book_title_hints=("Old World Bestiary.pdf",),
            page_hints=("printed page 99",),
        ),
        min_accepted_hits=1,
        required=True,
    )

    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="A page-level source citation.",
                object_type="page_fallback",
                object_title=None,
                source_object_id=None,
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].reason_code == "topical_evidence"


def test_subjectless_page_evidence_without_hints_fails_closed() -> None:
    evidence_requirement = requirement(
        requirement_type="page_evidence",
        subject=subject_constraint(canonical=None, include_terms=("page",)),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (hit(context_text="A page-level source citation.", object_title=None),),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "generic_subject_only"


def test_subjectless_page_evidence_with_only_book_hint_fails_closed() -> None:
    evidence_requirement = agent_planning.EvidenceRequirement(
        id="page_lookup",
        requirement_type="page_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical=None,
            surface=None,
            include_terms=("page",),
            book_title_hints=("Old World Bestiary.pdf",),
        ),
        min_accepted_hits=1,
        required=True,
    )

    result = evidence_validation.validate_hits_for_requirement(
        (hit(context_text="Unrelated page-level source citation.", object_title=None),),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "generic_subject_only"


def test_subjectless_page_evidence_with_only_page_hint_fails_closed() -> None:
    evidence_requirement = agent_planning.EvidenceRequirement(
        id="page_lookup",
        requirement_type="page_evidence",
        subject=agent_planning.SubjectConstraint(
            canonical=None,
            surface=None,
            include_terms=("page",),
            page_hints=("printed page 99",),
        ),
        min_accepted_hits=1,
        required=True,
    )

    result = evidence_validation.validate_hits_for_requirement(
        (hit(context_text="Unrelated page-level source citation.", object_title=None),),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "generic_subject_only"


def test_structural_multi_word_page_fallback_can_match_phrase_in_body() -> None:
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="Black Orc", include_terms=("Black Orc",)),
        object_type_hints=("stat_block",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="Black Orc profile M 4 WS 35 BS 25 S 40 T 45 W 13.",
                object_type="page_fallback",
                object_title=None,
                source_object_id=None,
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "sufficient"
    assert result.judgments[0].reason_code == "statline_evidence"


def test_table_row_requires_stat_fields_for_statline_requirement() -> None:
    table_row = hit(
        object_type="table_row",
        object_title="Harpy",
        context_text="Harpy | wings | mountain lair",
    )
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="harpy", include_terms=("harpy",)),
        required_terms=("harpy",),
        object_type_hints=("table_row",),
    )

    result = evidence_validation.validate_hits_for_requirement(
        (table_row,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "missing_statline_fields"


def test_stat_profile_link_hydration_stays_inside_checked_scope(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_book(config)
    insert_source_object(
        config,
        object_id="harpy-profile",
        book_id="bestiary",
        page_id="bestiary:101",
        object_type="npc_profile",
        title="Harpy",
        text="Harpy profile.",
    )
    insert_source_object(
        config,
        object_id="harpy-stat-linked",
        book_id="bestiary",
        page_id="bestiary:101",
        object_type="stat_block",
        title="Harpy Statistics",
        text="Harpy M 4 WS 35 BS 0 S 31 T 30 Ag 42 Int 18 WP 25 Fel 10.",
    )
    insert_source_object_link(
        config,
        link_id="harpy-profile-stat",
        from_object_id="harpy-profile",
        to_object_id="harpy-stat-linked",
        link_type="stat_profile",
    )
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="harpy", include_terms=("harpy",)),
        required_terms=("harpy",),
        object_type_hints=("npc_profile", "stat_block"),
    )

    checked_result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                object_type="npc_profile",
                object_title="Harpy",
                context_text="Harpy profile.",
                source_object_id="harpy-profile",
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
        config=config,
    )

    assert checked_result.status == "sufficient"
    assert checked_result.judgments[0].status == "accepted"

    with initialize_database(config.db_path) as connection:
        with connection:
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
                values ('unchecked', 'core', 'Unchecked Book', 'Rules',
                        'unchecked.pdf', '/source/unchecked.pdf',
                        '/managed/unchecked.pdf', 'source-unchecked',
                        'managed-unchecked', 1, 'copied', 'imported', 'indexed',
                        'not_scanned', '2026-06-09T00:00:00Z',
                        '2026-06-09T00:00:00Z')
                """
            )
            connection.execute(
                """
                insert into pages (
                  id,
                  book_id,
                  page_number,
                  page_label,
                  extraction_method,
                  embedded_text_chars,
                  text_chars,
                  word_count,
                  image_count,
                  ocr_attempted,
                  has_text
                )
                values ('unchecked:1', 'unchecked', 101, '101', 'ocr',
                        0, 20, 4, 0, 1, 1)
                """
            )
    insert_source_object(
        config,
        object_id="harpy-cross-profile",
        book_id="bestiary",
        page_id="bestiary:101",
        object_type="npc_profile",
        title="Harpy",
        text="Harpy profile.",
    )
    insert_source_object(
        config,
        object_id="unchecked-harpy-stat",
        book_id="unchecked",
        page_id="unchecked:1",
        object_type="stat_block",
        title="Harpy Statistics",
        text="Harpy M 4 WS 35 BS 0 S 31 T 30 Ag 42 Int 18 WP 25 Fel 10.",
    )
    insert_source_object_link(
        config,
        link_id="harpy-profile-unchecked-stat",
        from_object_id="harpy-cross-profile",
        to_object_id="unchecked-harpy-stat",
        link_type="stat_profile",
    )

    unchecked_result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                object_type="npc_profile",
                object_title="Harpy",
                context_text="Harpy profile.",
                source_object_id="harpy-cross-profile",
            ),
        ),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
        config=config,
    )

    assert unchecked_result.status == "insufficient"
    assert unchecked_result.judgments[0].reason_code == "missing_statline_fields"


def test_validate_hit_compatibility_and_empty_term_helpers() -> None:
    accepted = hit(context_text="Harpy stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10.")

    judgment = evidence_validation.validate_hit(
        accepted,
        subject="harpy",
        intent="statline_lookup",
        source_book_ids={"bestiary"},
    )
    unconstrained = evidence_validation.validate_hits_for_requirement(
        (accepted,),
        requirement=requirement(
            requirement_type="topical_evidence",
            subject=subject_constraint(canonical=None),
        ),
        source_book_ids=("bestiary",),
    )

    assert judgment.status == "accepted"
    assert evidence_validation.hit_mentions_subject(accepted, "the") is True
    assert evidence_validation.hit_mentions_subject(accepted, "harpy") is True
    assert unconstrained.status == "sufficient"
    assert evidence_validation.text_contains_term("harpy", "") is False


def test_record_validation_persists_judgments_and_updates_thread_context(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    (
        thread_id,
        user_message_id,
        model_run_id,
        research_run_id,
        retrieval_run_id,
    ) = create_research_run(config)
    accepted = hit(context_text="Harpy stat_block: M 4 WS 31 BS 0 S 31 T 30 W 10.")
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="harpy", include_terms=("harpy",)),
        required_terms=("harpy",),
        object_type_hints=("stat_block",),
    )
    result = evidence_validation.validate_hits_for_requirement(
        (accepted,),
        requirement=evidence_requirement,
        source_book_ids=("bestiary",),
    )
    plan = chat_store.record_familiar_research_plan(
        config,
        agent_planning.ResearchPlan(
            id="plan-1",
            research_run_id=research_run_id,
            revision=1,
            intent="statline_lookup",
            plan_summary="Find Harpy statline evidence.",
            subject=evidence_requirement.subject,
            requirements=(evidence_requirement,),
            planned_actions=(),
        ),
    )

    judgments = evidence_validation.record_evidence_judgments(
        config,
        research_run_id=research_run_id,
        research_plan_id=plan.id,
        requirement_id=evidence_requirement.id,
        retrieval_run_id=retrieval_run_id,
        validation=result,
    )
    context = evidence_validation.update_thread_context_from_validation(
        config,
        thread_id=thread_id,
        validation=result,
        subject="harpy",
        intent="statline_lookup",
        updated_from_message_id=user_message_id,
        updated_from_model_run_id=model_run_id,
    )

    assert len(judgments) == 1
    assert judgments[0].status == "accepted"
    assert judgments[0].research_plan_id == plan.id
    assert judgments[0].requirement_id == evidence_requirement.id
    assert judgments[0].subject_constraint == {
        "canonical": "harpy",
        "subject_terms": ["harpy"],
        "subject_aliases": [],
        "excluded_terms": [],
        "required_terms": [],
        "structural_terms": ["stat", "block"],
        "object_type_hints": ["stat_block"],
        "book_title_hints": [],
        "page_hints": [],
        "min_accepted_hits": 1,
    }
    assert judgments[0].constraint_status == "passed"
    assert context is not None
    assert context.active_subject == "harpy"
    assert context.active_intent == "statline_lookup"
    assert context.active_book_id == "bestiary"
    assert context.active_printed_page_label == "99"
    assert context.active_pdf_page_number == 101
    assert context.active_source_object_id == "harpy-stat"


def test_insufficient_validation_does_not_update_thread_context(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    (
        thread_id,
        user_message_id,
        model_run_id,
        _research_run_id,
        _retrieval_run_id,
    ) = create_research_run(config)
    existing = chat_store.upsert_chat_thread_context(
        config,
        thread_id,
        active_subject="harpy",
        active_intent="statline_lookup",
        active_book_id="bestiary",
        active_printed_page_label="99",
        active_pdf_page_number=101,
        updated_from_message_id=user_message_id,
        updated_from_model_run_id=model_run_id,
    )
    result = evidence_validation.validate_hits(
        (hit(context_text="Flying movement rules.", object_type="rule_section"),),
        subject="harpy",
        intent="statline_lookup",
        source_book_ids=("bestiary",),
    )

    context = evidence_validation.update_thread_context_from_validation(
        config,
        thread_id=thread_id,
        validation=result,
        subject="gor",
        intent="statline_lookup",
        updated_from_message_id="message-2",
        updated_from_model_run_id=model_run_id,
    )

    assert result.status == "insufficient"
    assert context == existing


def test_constraint_helpers_cover_structural_subject_and_link_miss_paths(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path)
    seed_book(config)
    structural = evidence_constraints.constraint_from_requirement(
        requirement(
            requirement_type="statline_evidence",
            subject=subject_constraint(canonical=None, include_terms=("Orc profile",)),
            object_type_hints=("stat_block",),
        )
    )

    assert structural.subject_terms == ("orc",)
    assert evidence_constraints.linked_zone_text(
        None,  # type: ignore[arg-type]
        hit(context_text="No object id.", source_object_id=None),
        source_book_ids={"bestiary"},
    ) == ("", "")
    assert evidence_constraints.linked_zone_text(
        None,  # type: ignore[arg-type]
        hit(context_text="Empty scope."),
        source_book_ids=set(),
    ) == ("", "")
    with initialize_database(config.db_path) as connection:
        assert evidence_constraints.linked_zone_text(
            connection,
            hit(
                context_text="Missing object.",
                source_object_id="missing-source-object",
            ),
            source_book_ids={"bestiary"},
        ) == ("", "")
        connection.execute(
            """
            update source_objects
            set metadata_json = '{"parent_title": "Parent Profile"}'
            where id = 'harpy-stat'
            """
        )
        identity_text, _stat_text = evidence_constraints.linked_zone_text(
            connection,
            hit(context_text="Hydrate parent metadata."),
            source_book_ids={"bestiary"},
        )
        assert "Parent Profile" in identity_text
    assert evidence_constraints.parent_title_from_metadata(
        '{"parent_title": "Parent Profile"}'
    ) == "Parent Profile"
    assert evidence_constraints.text_matches_any_term(
        "Harpy profile",
        ("orc", "harpy"),
    )
    assert evidence_constraints.meaningful_required_tokens("WS and profile") == (
        "profile",
    )


def test_required_terms_and_helper_edges_are_rejected_when_missing() -> None:
    result = evidence_validation.validate_hits_for_requirement(
        (
            hit(
                context_text="Harpy profile M 4 WS 31 BS 0 S 31 T 30 W 10.",
            ),
        ),
        requirement=requirement(
            requirement_type="statline_evidence",
            subject=subject_constraint(canonical="Harpy", include_terms=("Harpy",)),
            required_terms=("poison",),
            object_type_hints=("stat_block",),
        ),
        source_book_ids=("bestiary",),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "missing_required_terms"
    assert evidence_validation.zones_text(None) == ""
    assert evidence_validation.subject_evidence_text(None) == ""
    assert evidence_validation.subject_identity_text(None) == ""
    assert evidence_validation.text_matches_term_or_tokens(
        "critical hit",
        "critical hit",
    )
    assert evidence_validation.text_matches_term_or_tokens(
        "critical hit table",
        "critical table",
    )


def test_subject_match_reason_edges_cover_identity_and_missing_zones() -> None:
    evidence_requirement = requirement(
        requirement_type="statline_evidence",
        subject=subject_constraint(canonical="Black Orc", include_terms=("Black Orc",)),
        object_type_hints=("stat_block",),
    )
    source_hit = hit(
        context_text="Profile M 4 WS 31 BS 21 S 35 T 40 W 12.",
        object_title="Black Orc",
    )
    zones = evidence_constraints.build_evidence_zones(
        None,
        source_hit,
        source_book_ids={"bestiary"},
    )
    constraint = evidence_constraints.constraint_from_requirement(evidence_requirement)

    assert evidence_validation.hit_matches_requirement_subject(
        source_hit,
        evidence_requirement,
        zones,
    )
    assert (
        evidence_validation.requirement_subject_match_reason(
            source_hit,
            constraint,
            zones,
        )
        == "matched"
    )
    assert (
        evidence_validation.corrective_subject_match_reason(
            constraint,
            None,
        )
        == "subject_mismatch"
    )
    assert (
        evidence_validation.requirement_subject_match_reason(
            hit(
                context_text="Common Orc profile M 4 WS 31 BS 21 S 35 T 40 W 12.",
                object_type="page_fallback",
                object_title=None,
                source_object_id=None,
            ),
            constraint,
            None,
        )
        == "subject_mismatch"
    )

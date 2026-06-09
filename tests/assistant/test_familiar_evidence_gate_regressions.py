from __future__ import annotations

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant import evidence_validation
from wfrp_companion.assistant import retrieval
from wfrp_companion.assistant.evidence import RetrievedHit


def requirement(
    *,
    requirement_id: str,
    subject: str,
    requirement_type: agent_planning.RequirementType = "statline_evidence",
    required_terms: tuple[str, ...] = (),
    excluded_terms: tuple[str, ...] = (),
    object_type_hints: tuple[str, ...] = ("stat_block", "npc_profile"),
    book_title_hints: tuple[str, ...] = (),
    page_hints: tuple[str, ...] = (),
) -> agent_planning.EvidenceRequirement:
    return agent_planning.EvidenceRequirement(
        id=requirement_id,
        requirement_type=requirement_type,
        subject=agent_planning.SubjectConstraint(
            canonical=subject,
            surface=subject,
            include_terms=(subject,),
            exclude_terms=(),
            book_title_hints=book_title_hints,
            page_hints=page_hints,
        ),
        required_terms=required_terms,
        excluded_terms=excluded_terms,
        object_type_hints=object_type_hints,
        min_accepted_hits=1,
        required=True,
    )


def hit(
    *,
    subject: str,
    book_id: str = "synthetic-bestiary",
    title: str = "Synthetic Bestiary",
    page_number: int = 104,
    page_label: str | None = "104",
    context_text: str | None = None,
    object_type: str = "stat_block",
    object_title: str | None = None,
    heading_path: tuple[str, ...] = (),
    rank_reasons: tuple[str, ...] = ("candidate:source_object_fts",),
) -> RetrievedHit:
    text = context_text or f"{subject} profile M 4 WS 31 BS 21 S 35 T 40 W 12."
    return RetrievedHit(
        book_id=book_id,
        title=title,
        category="Synthetic",
        page_id=f"{book_id}:{page_number}",
        page_number=page_number,
        pdf_page_number=page_number,
        page_label=page_label,
        snippet=text,
        score=1.0,
        rank=1,
        context_text=text,
        source_object_id=f"{book_id}:{subject.casefold().replace(' ', '-')}",
        object_type=object_type,
        object_title=object_title or subject,
        heading_path=heading_path,
        page_start=page_number,
        page_end=page_number,
        page_range_label=page_label,
        confidence=0.9,
        rank_reasons=rank_reasons,
    )


def validate(
    retrieved: RetrievedHit,
    evidence_requirement: agent_planning.EvidenceRequirement,
) -> evidence_validation.EvidenceValidationResult:
    return evidence_validation.validate_hits_for_requirement(
        (retrieved,),
        requirement=evidence_requirement,
        source_book_ids=(retrieved.book_id,),
    )


def test_generic_career_profile_rejected_for_named_creature_statline() -> None:
    result = validate(
        hit(
            subject="Ambassador",
            book_id="synthetic-careers",
            title="Synthetic Careers",
            context_text="Ambassador profile M 4 WS 31 BS 31 S 30 T 30 W 11.",
            object_type="npc_profile",
        ),
        requirement(requirement_id="orc_stats", subject="Orc"),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "subject_mismatch"


def test_race_profile_rejected_for_named_npc_statline() -> None:
    result = validate(
        hit(
            subject="Human",
            context_text="Human profile M 4 WS 30 BS 30 S 30 T 30 W 11.",
            object_type="npc_profile",
            object_title="Race: Human",
        ),
        requirement(requirement_id="black_knight_stats", subject="Black Knight"),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "subject_mismatch"


def test_table_query_prefers_actual_table_over_prose_mention() -> None:
    table_candidate = retrieval.EvidenceCandidate(
        book_id="synthetic-rules",
        title="Synthetic Rules",
        category="Synthetic",
        page_id="synthetic-rules:12",
        page_number=12,
        pdf_page_number=12,
        page_label=None,
        page_start=12,
        page_end=12,
        page_range_label=None,
        snippet="hit location table",
        base_score=-8,
        context_text="d100 Location\n01-15 Head\n16-35 Arm",
        channel="source_object_fts",
        source_object_id="synthetic:hit-location-table",
        object_type="table",
        object_title="Hit Location",
        confidence=0.9,
        rank_reasons=("fusion:rrf=0.01",),
    )
    prose_candidate = retrieval.EvidenceCandidate(
        book_id="synthetic-rules",
        title="Synthetic Rules",
        category="Synthetic",
        page_id="synthetic-rules:13",
        page_number=13,
        pdf_page_number=13,
        page_label=None,
        page_start=13,
        page_end=13,
        page_range_label=None,
        snippet="hit location table",
        base_score=-4,
        context_text="This prose paragraph mentions a hit location table.",
        channel="source_object_fts",
        source_object_id="synthetic:hit-location-mention",
        object_type="rule_section",
        object_title="Combat Notes",
        confidence=0.9,
        rank_reasons=("fusion:rrf=0.04",),
    )

    ranked = retrieval.rerank_candidates(
        (prose_candidate, table_candidate),
        retrieval.plan_query("hit location table", ()),
    )

    assert ranked[0][0].source_object_id == "synthetic:hit-location-table"


def test_heading_only_entity_match_is_not_selected_over_direct_match() -> None:
    heading_only = retrieval.EvidenceCandidate(
        book_id="synthetic-adventure",
        title="Synthetic Adventure",
        category="Synthetic",
        page_id="synthetic-adventure:45",
        page_number=45,
        pdf_page_number=45,
        page_label=None,
        page_start=45,
        page_end=45,
        page_range_label=None,
        snippet="",
        base_score=-5,
        context_text="A different character appears in this paragraph.",
        channel="source_object_fts",
        source_object_id="synthetic:heading-only",
        object_type="rule_section",
        object_title="Unrelated Scene",
        heading_path=("Chapter: The Black Knight",),
        confidence=0.9,
        rank_reasons=("fusion:rrf=0.05",),
    )
    direct = retrieval.EvidenceCandidate(
        book_id="synthetic-adventure",
        title="Synthetic Adventure",
        category="Synthetic",
        page_id="synthetic-adventure:38",
        page_number=38,
        pdf_page_number=38,
        page_label=None,
        page_start=38,
        page_end=38,
        page_range_label=None,
        snippet="",
        base_score=-8,
        context_text="The Black Knight profile M 4 WS 45 BS 35 S 35 T 35 W 13.",
        channel="source_object_fts",
        source_object_id="synthetic:direct-black-knight",
        object_type="npc_profile",
        object_title="The Black Knight",
        heading_path=("Chapter: Encounters",),
        confidence=0.9,
        rank_reasons=("fusion:rrf=0.01",),
    )

    ranked = retrieval.rerank_candidates(
        (heading_only, direct),
        retrieval.plan_query("black knight profile", ()),
    )

    assert [candidate.source_object_id for candidate, _score, _reasons in ranked] == [
        "synthetic:direct-black-knight"
    ]


def test_vector_similar_wrong_entity_does_not_bypass_evidence_validation() -> None:
    result = validate(
        hit(
            subject="Black Knight",
            context_text="Black Knight profile M 4 WS 45 BS 35 S 35 T 35 W 13.",
            rank_reasons=("candidate:vector", "vector_provider:synthetic"),
        ),
        requirement(requirement_id="black_orc_stats", subject="Black Orc"),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "subject_mismatch"


def test_multi_word_subject_requires_phrase_not_scattered_terms() -> None:
    result = validate(
        hit(
            subject="Black Knight",
            object_title="Black Knight",
            context_text=(
                "Black Knight profile M 4 WS 45 BS 35 S 35 T 35 W 13. "
                "A nearby orc appears in unrelated notes."
            ),
        ),
        requirement(requirement_id="black_orc_stats", subject="Black Orc"),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "subject_mismatch"


def test_page_hint_mismatch_rejects_wrong_page_even_when_subject_matches() -> None:
    result = validate(
        hit(
            subject="Orc",
            page_number=103,
            page_label="103",
            context_text="Orc profile M 4 WS 35 BS 35 S 35 T 45 W 12.",
        ),
        requirement(
            requirement_id="orc_stats",
            subject="Orc",
            book_title_hints=("Synthetic Bestiary",),
            page_hints=("104",),
        ),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "page_hint_mismatch"


def test_book_hint_mismatch_rejects_wrong_book_even_when_subject_matches() -> None:
    result = validate(
        hit(
            subject="Orc",
            book_id="synthetic-careers",
            title="Synthetic Careers",
            context_text="Orc profile M 4 WS 35 BS 35 S 35 T 45 W 12.",
        ),
        requirement(
            requirement_id="orc_stats",
            subject="Orc",
            book_title_hints=("Synthetic Bestiary",),
        ),
    )

    assert result.status == "insufficient"
    assert result.judgments[0].reason_code == "book_hint_mismatch"

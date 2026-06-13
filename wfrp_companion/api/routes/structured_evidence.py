from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from wfrp_companion.api import errors
from wfrp_companion.api.dependencies import ConfigDependency
from wfrp_companion.api.schemas import (
    StructuredCandidateDetailResponse,
    StructuredCandidateListResponse,
    StructuredCandidateSummaryResponse,
    StructuredCorrectionRequest,
    StructuredObservationDetailResponse,
    StructuredReviewRequest,
    StructuredReviewResultResponse,
    StructuredReviewSummaryResponse,
)
from wfrp_companion.structured_evidence import store


router = APIRouter(tags=["structured-evidence"])


@router.get(
    "/structured-evidence/review/summary",
    response_model=StructuredReviewSummaryResponse,
)
def get_structured_review_summary(
    config: ConfigDependency,
) -> StructuredReviewSummaryResponse:
    summary = store.structured_review_summary(config)
    return StructuredReviewSummaryResponse(**summary.__dict__)


@router.get(
    "/structured-evidence/candidates",
    response_model=StructuredCandidateListResponse,
)
def list_structured_candidates(
    config: ConfigDependency,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> StructuredCandidateListResponse:
    candidates = store.list_structured_candidates(
        config,
        status=status,
        limit=limit,
    )
    return StructuredCandidateListResponse(
        candidates=[
            StructuredCandidateSummaryResponse(
                **{
                    **candidate.__dict__,
                    "suspicious_flags": list(candidate.suspicious_flags),
                }
            )
            for candidate in candidates
        ]
    )


@router.get(
    "/structured-evidence/candidates/{candidate_id}",
    response_model=StructuredCandidateDetailResponse,
)
def get_structured_candidate(
    candidate_id: str,
    config: ConfigDependency,
) -> StructuredCandidateDetailResponse:
    try:
        detail = store.get_structured_candidate_detail(config, candidate_id)
    except store.StructuredEvidenceError as error:
        raise errors.structured_evidence_error(error) from error
    return structured_candidate_detail_response(detail)


@router.post(
    "/structured-evidence/candidates/{candidate_id}/approve",
    response_model=StructuredReviewResultResponse,
)
def approve_structured_candidate(
    candidate_id: str,
    request: StructuredReviewRequest,
    config: ConfigDependency,
) -> StructuredReviewResultResponse:
    try:
        result = store.approve_structured_candidate(
            config,
            candidate_id,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except store.StructuredEvidenceError as error:
        raise errors.structured_evidence_error(error) from error
    return StructuredReviewResultResponse(**result.__dict__)


@router.post(
    "/structured-evidence/candidates/{candidate_id}/correct",
    response_model=StructuredReviewResultResponse,
)
def correct_structured_candidate(
    candidate_id: str,
    request: StructuredCorrectionRequest,
    config: ConfigDependency,
) -> StructuredReviewResultResponse:
    try:
        result = store.correct_structured_candidate(
            config,
            candidate_id,
            request.payload_json,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except store.StructuredEvidenceError as error:
        raise errors.structured_evidence_error(error) from error
    return StructuredReviewResultResponse(**result.__dict__)


@router.post(
    "/structured-evidence/candidates/{candidate_id}/reject",
    response_model=StructuredReviewResultResponse,
)
def reject_structured_candidate(
    candidate_id: str,
    request: StructuredReviewRequest,
    config: ConfigDependency,
) -> StructuredReviewResultResponse:
    try:
        result = store.reject_structured_candidate(
            config,
            candidate_id,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except store.StructuredEvidenceError as error:
        raise errors.structured_evidence_error(error) from error
    return StructuredReviewResultResponse(**result.__dict__)


def structured_candidate_detail_response(
    detail: store.StructuredCandidateDetail,
) -> StructuredCandidateDetailResponse:
    return StructuredCandidateDetailResponse(
        id=detail.id,
        book_id=detail.book_id,
        book_title=detail.book_title,
        object_shape=detail.object_shape,
        content_kind=detail.content_kind,
        entity_kind=detail.entity_kind,
        canonical_name=detail.canonical_name,
        title=detail.title,
        table_number=detail.table_number,
        table_number_normalized=detail.table_number_normalized,
        page_start=detail.page_start,
        page_end=detail.page_end,
        printed_page_start=detail.printed_page_start,
        printed_page_end=detail.printed_page_end,
        confidence=detail.confidence,
        suspicious_flags=list(detail.suspicious_flags),
        status=detail.status,
        updated_at=detail.updated_at,
        primary_page_id=detail.primary_page_id,
        primary_source_object_id=detail.primary_source_object_id,
        heading_path=list(detail.heading_path),
        payload_json=detail.payload_json,
        text_snapshot_sha256=detail.text_snapshot_sha256,
        structured_extractor_version=detail.structured_extractor_version,
        observations=[
            StructuredObservationDetailResponse(**observation.__dict__)
            for observation in detail.observations
        ],
    )

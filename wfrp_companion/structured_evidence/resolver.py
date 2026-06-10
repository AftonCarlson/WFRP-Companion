from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from wfrp_companion.assistant.evidence import EvidenceCandidate
from wfrp_companion.assistant.evidence import load_page_range_label
from wfrp_companion.assistant.evidence_constraints import BOOK_HINT_STOP_TERMS
from wfrp_companion.assistant.evidence_constraints import EvidenceConstraint
from wfrp_companion.assistant.evidence_constraints import PAGE_HINT_STOP_TERMS
from wfrp_companion.assistant.evidence_constraints import text_matches_hint
from wfrp_companion.assistant.query_planner import meaningful_tokens
from wfrp_companion.library.page_labels import load_calibrated_printed_page_label
from wfrp_companion.structured_evidence.models import normalize_structured_alias
from wfrp_companion.structured_evidence.models import normalize_table_number
from wfrp_companion.structured_evidence.payloads import payload_hash
from wfrp_companion.structured_evidence.store import structured_evidence_snapshot_sha256


ACTIVE_LOOKUP_POLICIES = frozenset({"required", "allowed", "supporting_only"})
STRUCTURED_OBJECT_TYPES = {
    "structured_table": "validated_structured_table",
    "profile_bundle": "validated_profile_bundle",
}


@dataclass(frozen=True)
class StructuredResolverResult:
    candidates: tuple[EvidenceCandidate, ...]
    skip_reason: str | None = None


def resolve_validated_structured_candidates(
    connection: sqlite3.Connection,
    *,
    query: str,
    book_ids: tuple[str, ...],
    constraint: EvidenceConstraint | None,
    limit: int,
) -> StructuredResolverResult:
    if constraint is None:
        return StructuredResolverResult((), "no_requirement_policy")
    policy = constraint.structured_lookup_policy
    if policy not in ACTIVE_LOOKUP_POLICIES:
        return StructuredResolverResult((), f"policy_{policy}")
    if not book_ids:
        return StructuredResolverResult((), "no_source_books")
    if limit <= 0:
        return StructuredResolverResult((), "limit_zero")

    rows = active_validated_rows(connection, book_ids=book_ids)
    matches: list[EvidenceCandidate] = []
    for row in rows:
        aliases = aliases_for_validated_object(connection, row["id"])
        if not row_matches_constraint(row, aliases, constraint):
            continue
        if not row_matches_query(row, aliases, query, constraint):
            continue
        matches.append(
            candidate_from_validated_row(
                connection,
                row,
                aliases=aliases,
                policy=policy,
                base_score=-100.0 + len(matches),
            )
        )
        if len(matches) >= limit:
            break
    if not matches:
        return StructuredResolverResult((), "no_active_match")
    return StructuredResolverResult(tuple(matches), None)


def active_validated_rows(
    connection: sqlite3.Connection,
    *,
    book_ids: tuple[str, ...],
) -> tuple[sqlite3.Row, ...]:
    if not book_ids:
        return ()
    placeholders = ",".join("?" for _ in book_ids)
    rows = tuple(
        connection.execute(
            f"""
            select
              validated_structured_objects.*,
              books.title as book_title,
              books.category as book_category,
              pages.page_number as pdf_page_number,
              pages.page_label as page_label
            from validated_structured_objects
            join books on books.id = validated_structured_objects.book_id
            join pages on pages.id = validated_structured_objects.primary_page_id
            where validated_structured_objects.validation_status = 'active'
              and validated_structured_objects.book_id in ({placeholders})
            order by
              validated_structured_objects.book_id,
              validated_structured_objects.page_start,
              validated_structured_objects.object_shape,
              coalesce(
                validated_structured_objects.table_number_normalized,
                validated_structured_objects.canonical_name,
                validated_structured_objects.title,
                validated_structured_objects.id
              )
            """,
            book_ids,
        ).fetchall()
    )
    current_snapshots = {
        book_id: structured_evidence_snapshot_sha256(connection, book_id)
        for book_id in book_ids
    }
    return tuple(
        row
        for row in rows
        if row["source_snapshot_sha256"] == current_snapshots.get(row["book_id"])
    )


def aliases_for_validated_object(
    connection: sqlite3.Connection,
    validated_object_id: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        select alias_normalized
        from validated_structured_object_aliases
        where validated_object_id = ?
        order by confidence desc, alias_normalized
        """,
        (validated_object_id,),
    ).fetchall()
    return tuple(row["alias_normalized"] for row in rows if row["alias_normalized"])


def row_matches_constraint(
    row: sqlite3.Row,
    aliases: tuple[str, ...],
    constraint: EvidenceConstraint,
) -> bool:
    if constraint.structured_object_shape_hints:
        allowed_shapes = {
            normalized_shape_hint(hint)
            for hint in constraint.structured_object_shape_hints
        }
        allowed_shapes.discard(None)
        if allowed_shapes and row["object_shape"] not in allowed_shapes:
            return False
    if constraint.structured_content_kind_hints and row["content_kind"] not in {
        hint.casefold() for hint in constraint.structured_content_kind_hints
    }:
        return False
    if constraint.structured_entity_kind_hints and row["entity_kind"] not in {
        hint.casefold() for hint in constraint.structured_entity_kind_hints
    }:
        return False
    if constraint.table_number_hints and not row_matches_table_hints(
        row,
        aliases,
        constraint.table_number_hints,
    ):
        return False
    if constraint.book_title_hints and not any(
        text_matches_hint(
            book_scope_text(row),
            hint,
            ignored_terms=BOOK_HINT_STOP_TERMS,
        )
        for hint in constraint.book_title_hints
    ):
        return False
    if constraint.page_hints and not any(
        text_matches_hint(
            page_scope_text(row),
            hint,
            ignored_terms=PAGE_HINT_STOP_TERMS,
        )
        for hint in constraint.page_hints
    ):
        return False
    return True


def row_matches_query(
    row: sqlite3.Row,
    aliases: tuple[str, ...],
    query: str,
    constraint: EvidenceConstraint,
) -> bool:
    query_text = normalize_structured_alias(
        " ".join(
            part
            for part in (
                query,
                constraint.canonical_subject or "",
                " ".join(constraint.subject_terms),
                " ".join(constraint.subject_aliases),
                " ".join(constraint.table_number_hints),
            )
            if part
        )
    )
    if not query_text:
        return False
    identity_text = structured_identity_text(row, aliases)
    if any(alias and phrase_contains(query_text, alias) for alias in aliases):
        return True
    if row["table_number_normalized"]:
        table_number_alias = normalize_structured_alias(row["table_number_normalized"])
        if table_number_alias and phrase_contains(query_text, table_number_alias):
            return True
    query_terms = set(meaningful_tokens(query_text))
    if not query_terms:
        return False
    identity_terms = set(meaningful_tokens(identity_text))
    overlap = query_terms.intersection(identity_terms)
    required_overlap = 1 if len(query_terms) == 1 else 2
    return len(overlap) >= required_overlap


def row_matches_table_hints(
    row: sqlite3.Row,
    aliases: tuple[str, ...],
    hints: tuple[str, ...],
) -> bool:
    row_number = row["table_number_normalized"] or ""
    normalized_row_numbers = {
        row_number,
        normalize_structured_alias(row_number),
    }
    for hint in hints:
        normalized_hint = normalize_table_number(hint)
        alias_hint = normalize_structured_alias(normalized_hint)
        if normalized_hint in normalized_row_numbers or alias_hint in aliases:
            return True
        if alias_hint in normalized_row_numbers:
            return True
    return False


def candidate_from_validated_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    aliases: tuple[str, ...],
    policy: str,
    base_score: float,
) -> EvidenceCandidate:
    payload = payload_from_row(row)
    page_label = load_calibrated_printed_page_label(
        connection,
        book_id=row["book_id"],
        page_number=int(row["page_start"]),
        fallback_label=row["printed_page_start"] or row["page_label"],
    )
    page_range_label = (
        row["printed_page_start"]
        if row["printed_page_start"] == row["printed_page_end"]
        else load_page_range_label(
            connection,
            book_id=row["book_id"],
            page_start=int(row["page_start"]),
            page_end=int(row["page_end"]),
        )
    )
    object_type = STRUCTURED_OBJECT_TYPES.get(row["object_shape"], "validated_structured")
    identity = row["title"] or row["canonical_name"] or row["table_number"] or row["id"]
    context_text = validated_context_text(row, aliases, payload)
    table_reason = (
        (f"validated_table_number:{row['table_number_normalized']}",)
        if row["table_number_normalized"]
        else ()
    )
    alias_reason = (f"validated_alias:{aliases[0]}",) if aliases else ()
    return EvidenceCandidate(
        book_id=row["book_id"],
        title=row["book_title"],
        category=row["book_category"],
        page_id=row["primary_page_id"],
        page_number=int(row["page_start"]),
        pdf_page_number=int(row["pdf_page_number"]),
        page_label=page_label,
        page_start=int(row["page_start"]),
        page_end=int(row["page_end"]),
        page_range_label=page_range_label,
        snippet=identity,
        base_score=base_score,
        context_text=context_text,
        channel="validated_structured",
        source_object_id=row["primary_source_object_id"],
        object_type=object_type,
        object_title=identity,
        heading_path=tuple(json_string_list(row["heading_path_json"])),
        confidence=1.0,
        rank_reasons=(
            "candidate:validated_structured",
            "validated_structured:active",
            f"structured_policy:{policy}",
            f"validated_structured_object:{row['id']}",
            *table_reason,
            *alias_reason,
        ),
        text_snapshot_sha256=row["source_snapshot_sha256"],
        validated_structured_object_id=row["id"],
        validated_payload_schema_version=int(row["payload_schema_version"]),
        validated_payload_hash=payload_hash(payload),
        validated_validation_status=row["validation_status"],
        validated_source_snapshot_sha256=row["source_snapshot_sha256"],
        structured_lookup_policy=policy,
    )


def validated_context_text(
    row: sqlite3.Row,
    aliases: tuple[str, ...],
    payload: Mapping[str, Any],
) -> str:
    compact_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "\n".join(
        part
        for part in (
            f"Validated structured evidence: {row['title'] or row['canonical_name'] or row['id']}",
            f"Object shape: {row['object_shape']}",
            f"Structured terms: {structured_relevance_terms(row['object_shape'])}",
            f"Content kind: {row['content_kind']}",
            f"Entity kind: {row['entity_kind']}",
            f"Table number: {row['table_number'] or ''}",
            f"Aliases: {', '.join(aliases)}",
            compact_payload,
        )
        if part
    )


def structured_relevance_terms(object_shape: str) -> str:
    if object_shape == "profile_bundle":
        return "profile statline stats stat block"
    if object_shape == "structured_table":
        return "table chart structured table"
    return "structured evidence"


def structured_identity_text(row: sqlite3.Row, aliases: tuple[str, ...]) -> str:
    return normalize_structured_alias(
        " ".join(
            part
            for part in (
                row["title"] or "",
                row["canonical_name"] or "",
                row["table_number"] or "",
                row["table_number_normalized"] or "",
                row["content_kind"] or "",
                row["entity_kind"] or "",
                " ".join(aliases),
            )
            if part
        )
    )


def book_scope_text(row: sqlite3.Row) -> str:
    return " ".join(
        str(part)
        for part in (row["book_id"], row["book_title"], row["book_category"])
        if part
    )


def page_scope_text(row: sqlite3.Row) -> str:
    return " ".join(
        str(part)
        for part in (
            row["primary_page_id"],
            row["page_start"],
            row["page_end"],
            row["printed_page_start"],
            row["printed_page_end"],
            row["page_label"],
        )
        if part is not None
    )


def normalized_shape_hint(value: str) -> str | None:
    key = normalize_structured_alias(value).replace(" ", "_")
    if key in {"table", "validated_structured_table", "structured_table"}:
        return "structured_table"
    if key in {"profile", "profile_bundle", "validated_profile_bundle"}:
        return "profile_bundle"
    return key if key in STRUCTURED_OBJECT_TYPES else None


def phrase_contains(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    return phrase == text or phrase in text or text in phrase


def payload_from_row(row: sqlite3.Row) -> Mapping[str, Any]:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def json_string_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(item for item in parsed if isinstance(item, str))

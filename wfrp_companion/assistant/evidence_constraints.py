from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from wfrp_companion.assistant import agent_planning
from wfrp_companion.assistant.evidence import RetrievedHit
from wfrp_companion.assistant.query_planner import meaningful_tokens


ConstraintStatus = Literal["passed", "failed", "partial", "not_applicable"]

STRUCTURAL_CONSTRAINT_TERMS = frozenset(
    {
        "block",
        "blocks",
        "chart",
        "charts",
        "entry",
        "entries",
        "page",
        "pages",
        "profile",
        "profiles",
        "rule",
        "rules",
        "source",
        "sources",
        "stat",
        "statline",
        "statlines",
        "statistics",
        "stats",
        "table",
        "tables",
    }
)

STAT_FIELD_TERMS = frozenset(
    {
        "a",
        "ag",
        "bs",
        "fel",
        "fp",
        "int",
        "ip",
        "m",
        "mag",
        "s",
        "sb",
        "t",
        "tb",
        "w",
        "wp",
        "ws",
    }
)

SUBJECT_STOP_TERMS = frozenset(
    {
        "a",
        "about",
        "an",
        "find",
        "for",
        "give",
        "me",
        "of",
        "on",
        "show",
        "tell",
        "the",
        "their",
        "there",
    }
)

STRUCTURAL_REQUIREMENT_TYPES = {
    "statline_evidence",
    "page_evidence",
    "source_object_evidence",
}
BOOK_HINT_STOP_TERMS = frozenset({"book", "pdf", "source"})
PAGE_HINT_STOP_TERMS = frozenset({"p", "page", "pages", "pdf", "pg", "printed"})
TERM_RE = re.compile(r"(?u)\b[\w'-]+\b")


@dataclass(frozen=True)
class EvidenceConstraint:
    requirement_id: str
    requirement_type: str
    canonical_subject: str | None
    subject_terms: tuple[str, ...]
    subject_aliases: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    required_terms: tuple[str, ...]
    structural_terms: tuple[str, ...]
    object_type_hints: tuple[str, ...]
    book_title_hints: tuple[str, ...]
    page_hints: tuple[str, ...]
    min_accepted_hits: int

    @property
    def has_generic_subject_only(self) -> bool:
        if (
            self.requirement_type not in STRUCTURAL_REQUIREMENT_TYPES
            or self.subject_terms
        ):
            return False
        return not (
            self.requirement_type == "page_evidence"
            and self.book_title_hints
            and self.page_hints
        )

    def to_json(self) -> dict[str, object]:
        return {
            "canonical": self.canonical_subject,
            "subject_terms": list(self.subject_terms),
            "subject_aliases": list(self.subject_aliases),
            "excluded_terms": list(self.excluded_terms),
            "required_terms": list(self.required_terms),
            "structural_terms": list(self.structural_terms),
            "object_type_hints": list(self.object_type_hints),
            "book_title_hints": list(self.book_title_hints),
            "page_hints": list(self.page_hints),
            "min_accepted_hits": self.min_accepted_hits,
        }


@dataclass(frozen=True)
class EvidenceZones:
    identity_text: str
    direct_body_text: str
    structural_text: str
    page_scope_text: str
    linked_identity_text: str = ""
    linked_stat_text: str = ""


@dataclass(frozen=True)
class ConstraintDecision:
    status: ConstraintStatus
    reason_code: str
    reasons: tuple[str, ...]
    matched_subject_terms: tuple[str, ...] = ()
    matched_required_terms: tuple[str, ...] = ()
    matched_stat_fields: tuple[str, ...] = ()


def constraint_from_requirement(
    requirement: agent_planning.EvidenceRequirement,
) -> EvidenceConstraint:
    canonical_subject = normalized_subject(requirement.subject.canonical)
    subject_terms = subject_terms_from_canonical(canonical_subject)
    if canonical_subject is None and requirement.requirement_type in STRUCTURAL_REQUIREMENT_TYPES:
        subject_terms = filtered_identity_terms(requirement.subject.include_terms)

    subject_aliases = tuple(
        term
        for term in filtered_identity_terms(requirement.subject.include_terms)
        if term not in subject_terms
    )
    structural_terms = structural_terms_from_requirement(requirement)
    required_terms = tuple(
        term
        for term in normalized_terms(requirement.required_terms)
        if term not in subject_terms
        and term not in subject_aliases
        and term not in structural_terms
        and term not in STAT_FIELD_TERMS
        and term not in SUBJECT_STOP_TERMS
    )
    return EvidenceConstraint(
        requirement_id=requirement.id,
        requirement_type=requirement.requirement_type,
        canonical_subject=canonical_subject,
        subject_terms=subject_terms,
        subject_aliases=subject_aliases,
        excluded_terms=normalized_phrases(
            (*requirement.subject.exclude_terms, *requirement.excluded_terms)
        ),
        required_terms=tuple(dict.fromkeys(required_terms)),
        structural_terms=structural_terms,
        object_type_hints=tuple(dict.fromkeys(requirement.object_type_hints)),
        book_title_hints=tuple(dict.fromkeys(requirement.subject.book_title_hints)),
        page_hints=tuple(dict.fromkeys(requirement.subject.page_hints)),
        min_accepted_hits=requirement.min_accepted_hits,
    )


def normalized_subject(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def subject_terms_from_canonical(subject: str | None) -> tuple[str, ...]:
    if subject is None:
        return ()
    return filtered_identity_terms((subject,))


def filtered_identity_terms(values: Iterable[str]) -> tuple[str, ...]:
    terms: list[str] = []
    for term in normalized_terms(values):
        if (
            term in STRUCTURAL_CONSTRAINT_TERMS
            or term in STAT_FIELD_TERMS
            or term in SUBJECT_STOP_TERMS
        ):
            continue
        if term not in terms:
            terms.append(term)
    return tuple(terms)


def structural_terms_from_requirement(
    requirement: agent_planning.EvidenceRequirement,
) -> tuple[str, ...]:
    terms: list[str] = []
    values = (
        requirement.subject.canonical,
        *requirement.subject.include_terms,
        *requirement.required_terms,
        *requirement.object_type_hints,
    )
    for term in normalized_terms(value for value in values if value):
        if term in STRUCTURAL_CONSTRAINT_TERMS or term in STAT_FIELD_TERMS:
            if term not in terms:
                terms.append(term)
    return tuple(terms)


def normalized_terms(values: Iterable[str]) -> tuple[str, ...]:
    terms: list[str] = []
    for value in values:
        for token in normalized_tokens(value):
            if token not in terms:
                terms.append(token)
    return tuple(terms)


def normalized_tokens(value: str) -> tuple[str, ...]:
    expanded = value.replace("_", " ").replace("-", " ")
    tokens = [token.casefold() for token in TERM_RE.findall(expanded)]
    return tuple(token for token in tokens if token)


def normalized_object_type_key(value: str) -> str:
    return "_".join(normalized_tokens(value))


def normalized_phrases(values: Iterable[str]) -> tuple[str, ...]:
    phrases: list[str] = []
    for value in values:
        normalized = " ".join(normalized_tokens(value))
        if normalized and normalized not in phrases:
            phrases.append(normalized)
    return tuple(phrases)


def build_evidence_zones(
    connection: sqlite3.Connection | None,
    hit: RetrievedHit,
    *,
    source_book_ids: set[str],
) -> EvidenceZones:
    linked_identity_text = ""
    linked_stat_text = ""
    if connection is not None and hit.source_object_id is not None:
        linked_identity_text, linked_stat_text = linked_zone_text(
            connection,
            hit,
            source_book_ids=source_book_ids,
        )
    return EvidenceZones(
        identity_text=" ".join(
            part
            for part in (
                hit.object_title,
                " ".join(hit.heading_path),
            )
            if part
        ),
        direct_body_text=" ".join(part for part in (hit.snippet, hit.context_text) if part),
        structural_text=" ".join(
            part for part in (hit.object_type.replace("_", " "),) if part
        ),
        page_scope_text=" ".join(
            part
            for part in (
                hit.title,
                hit.page_range_label,
                hit.page_label,
                str(hit.pdf_page_number),
            )
            if part
        ),
        linked_identity_text=linked_identity_text,
        linked_stat_text=linked_stat_text,
    )


def linked_zone_text(
    connection: sqlite3.Connection,
    hit: RetrievedHit,
    *,
    source_book_ids: set[str],
) -> tuple[str, str]:
    if hit.source_object_id is None or not source_book_ids:
        return ("", "")
    row = connection.execute(
        """
        select title, metadata_json
        from source_objects
        where id = ?
          and book_id in ({})
        """.format(",".join("?" for _ in source_book_ids)),
        (hit.source_object_id, *sorted(source_book_ids)),
    ).fetchone()
    if row is None:
        return ("", "")
    identity_parts = [row["title"] or ""]
    metadata = row["metadata_json"] or ""
    parent_title = parent_title_from_metadata(metadata)
    if parent_title:
        identity_parts.append(parent_title)
    linked_rows = connection.execute(
        """
        select linked.title, linked.text, links.link_type
        from source_object_links links
        join source_objects linked
          on linked.id in (links.from_object_id, links.to_object_id)
        where ? in (links.from_object_id, links.to_object_id)
          and linked.id <> ?
          and links.link_type in ('stat_profile', 'table_row')
          and linked.book_id in ({})
        """.format(",".join("?" for _ in source_book_ids)),
        (hit.source_object_id, hit.source_object_id, *sorted(source_book_ids)),
    ).fetchall()
    stat_parts: list[str] = []
    for linked_row in linked_rows:
        identity_parts.append(linked_row["title"] or "")
        stat_parts.append(linked_row["text"] or "")
    return (" ".join(part for part in identity_parts if part), " ".join(stat_parts))


def parent_title_from_metadata(metadata_json: str) -> str | None:
    match = re.search(r'"parent_title"\s*:\s*"([^"]+)"', metadata_json)
    if match is None:
        return None
    return match.group(1)


def text_matches_phrase(text: str, phrase: str) -> bool:
    phrase_tokens = normalized_tokens(phrase)
    if not phrase_tokens:
        return False
    text_tokens = normalized_tokens(text)
    if len(phrase_tokens) == 1:
        return phrase_tokens[0] in text_tokens
    size = len(phrase_tokens)
    return any(
        tuple(text_tokens[index : index + size]) == phrase_tokens
        for index in range(0, max(0, len(text_tokens) - size + 1))
    )


def text_matches_hint(
    text: str,
    hint: str,
    *,
    ignored_terms: Iterable[str] = (),
) -> bool:
    ignored = {term.casefold() for term in ignored_terms}
    hint_tokens = tuple(
        token for token in normalized_tokens(hint) if token not in ignored
    )
    if not hint_tokens:
        return False
    text_tokens = normalized_tokens(text)
    if len(hint_tokens) == 1:
        return hint_tokens[0] in text_tokens
    size = len(hint_tokens)
    return any(
        tuple(text_tokens[index : index + size]) == hint_tokens
        for index in range(0, max(0, len(text_tokens) - size + 1))
    )


def text_matches_all_terms(text: str, terms: Iterable[str]) -> bool:
    return all(text_matches_phrase(text, term) for term in terms)


def text_matches_any_term(text: str, terms: Iterable[str]) -> bool:
    return any(text_matches_phrase(text, term) for term in terms)


def meaningful_required_tokens(term: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in meaningful_tokens(term)
        if token not in SUBJECT_STOP_TERMS and token not in STAT_FIELD_TERMS
    )

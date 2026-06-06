from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from wfrp_companion.config import AppConfig
from wfrp_companion.db.connection import initialize_database
from wfrp_companion.db.migrations import apply_pending_migrations
from wfrp_companion.source_objects.layout import LayoutPage, load_pdf_layout_pages
from wfrp_companion.source_objects.models import (
    SourceObject,
    deterministic_source_object_id,
)
from wfrp_companion.source_objects.store import (
    SourcePage,
    book_text_snapshot_sha256,
    claim_extraction_job,
    eligible_books,
    ensure_book_object_status,
    extraction_job_id,
    load_book_pages,
    mark_extraction_failed,
    object_status_current,
    recover_stale_running_jobs,
    replace_book_source_objects,
    utc_timestamp,
)


HEADING_RE = re.compile(r"^(chapter|part|section|appendix)\b", re.IGNORECASE)
INDEX_ENTRY_RE = re.compile(
    r"^(?P<title>[A-Za-z][A-Za-z0-9'’() /-]{1,80})\s*(?:\.{2,}|,)\s*"
    r"(?P<page>\d{1,4})$"
)
GLOSSARY_ENTRY_RE = re.compile(
    r"^(?P<title>[A-Za-z][A-Za-z0-9'’() /-]{1,80}):\s*(?P<body>.+)$"
)
CROSS_REFERENCE_RE = re.compile(
    r"\bsee(?: also)? (?P<title>[A-Za-z][A-Za-z0-9'’() /-]{1,80}?)"
    r"(?: on page (?P<page>\d{1,4}))?\.",
    re.IGNORECASE,
)
STAT_HEADER_TOKENS = frozenset(
    ("m", "ws", "bs", "s", "t", "w", "i", "a", "dex", "int", "wp", "fel")
)
PROFILE_FOLLOWUP_PREFIXES = (
    "skills:",
    "talents:",
    "traits:",
    "trappings:",
    "weapons:",
    "armour:",
    "armor:",
    "notes:",
)


@dataclass(frozen=True)
class ExtractionFailure:
    book_id: str
    reason: str


@dataclass(frozen=True)
class ExtractedBookSummary:
    book_id: str
    text_snapshot_sha256: str
    object_count: int


@dataclass(frozen=True)
class ExtractionSummary:
    discovered: int
    extracted: int
    skipped_current: int
    stale_recovered: int
    failed: int
    objects_written: int
    failures: tuple[ExtractionFailure, ...]
    book_summaries: tuple[ExtractedBookSummary, ...]


@dataclass(frozen=True)
class PendingSection:
    title: str
    heading_path: tuple[str, ...]
    page: SourcePage
    start: int
    end: int


@dataclass(frozen=True)
class LineSpan:
    text: str
    stripped: str
    start: int
    end: int


def extract_source_object_library(
    config: AppConfig,
    *,
    book_ids: tuple[str, ...] | None = None,
    force: bool = False,
    retry_running: bool = False,
    stale_running_minutes: int = 30,
) -> ExtractionSummary:
    if not config.db_path.exists():
        initialize_database(config.db_path).close()
    apply_pending_migrations(config.db_path)
    with initialize_database(config.db_path) as connection:
        stale_recovered = recover_stale_running_jobs(
            connection,
            retry_running=retry_running,
            stale_running_minutes=stale_running_minutes,
        )
        books = eligible_books(connection, book_ids=book_ids)
        extracted = 0
        skipped_current = 0
        failed = 0
        objects_written = 0
        failures: list[ExtractionFailure] = []
        book_summaries: list[ExtractedBookSummary] = []

        for book in books:
            now = utc_timestamp()
            text_snapshot = book_text_snapshot_sha256(connection, book.book_id)
            ensure_book_object_status(connection, book_id=book.book_id, now=now)
            if (
                not force
                and object_status_current(
                    connection,
                    book_id=book.book_id,
                    text_snapshot_sha256=text_snapshot,
                )
            ):
                skipped_current += 1
                continue

            if not claim_extraction_job(
                connection,
                book_id=book.book_id,
                text_snapshot_sha256=text_snapshot,
                force=force,
                now=now,
            ):
                continue

            job_id = extraction_job_id(book.book_id, text_snapshot)
            try:
                pages = load_book_pages(connection, book.book_id)
                layout_pages = load_pdf_layout_pages(
                    Path(book.managed_pdf_path),
                    page_count=book.page_count,
                )
                source_objects = extract_objects_from_pages(
                    book_id=book.book_id,
                    text_snapshot_sha256=text_snapshot,
                    pages=pages,
                    layout_pages=layout_pages,
                )
                replace_book_source_objects(
                    connection,
                    book_id=book.book_id,
                    text_snapshot_sha256=text_snapshot,
                    source_objects=source_objects,
                    job_id=job_id,
                    now=utc_timestamp(),
                )
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                mark_extraction_failed(
                    connection,
                    book_id=book.book_id,
                    job_id=job_id,
                    error=error,
                    now=utc_timestamp(),
                )
                failures.append(ExtractionFailure(book.book_id, error))
                failed += 1
                continue

            extracted += 1
            objects_written += len(source_objects)
            book_summaries.append(
                ExtractedBookSummary(
                    book_id=book.book_id,
                    text_snapshot_sha256=text_snapshot,
                    object_count=len(source_objects),
                )
            )

        return ExtractionSummary(
            discovered=len(books),
            extracted=extracted,
            skipped_current=skipped_current,
            stale_recovered=stale_recovered,
            failed=failed,
            objects_written=objects_written,
            failures=tuple(failures),
            book_summaries=tuple(book_summaries),
        )


def extract_objects_from_pages(
    *,
    book_id: str,
    text_snapshot_sha256: str,
    pages: tuple[SourcePage, ...],
    layout_pages: tuple[LayoutPage, ...],
) -> tuple[SourceObject, ...]:
    layout_by_page = {layout.page_number: layout for layout in layout_pages}
    source_objects: list[SourceObject] = []

    for page in pages:
        if not page.text.strip():
            continue
        page_layout = layout_by_page.get(page.page_number)
        metadata = page_metadata(page, page_layout)
        sections = extract_rule_sections_from_page(
            page=page,
            book_id=book_id,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata=metadata,
        )
        structured_objects = extract_structured_objects_from_page(
            page=page,
            book_id=book_id,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata=metadata,
        )
        if sections:
            source_objects.extend(sections)
        if structured_objects:
            source_objects.extend(structured_objects)
        covered_spans = tuple(
            (section.char_start or 0, section.char_end or 0)
            for section in (*sections, *structured_objects)
        )
        source_objects.extend(
            build_page_chunks(
                page=page,
                book_id=book_id,
                text_snapshot_sha256=text_snapshot_sha256,
                metadata=metadata,
                covered_spans=covered_spans,
            )
        )

    return tuple(source_objects)


def extract_rule_sections_from_page(
    *,
    page: SourcePage,
    book_id: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
) -> tuple[SourceObject, ...]:
    heading_positions = heading_lines(page.text)
    if not heading_positions:
        return ()

    current_chapter: str | None = None
    current_chapter_start: int | None = None
    previous_level: int | None = None
    candidates: list[PendingSection] = []
    for index, (start, end, heading) in enumerate(heading_positions):
        level = heading_level(heading)
        if level == 1:
            current_chapter = heading
            current_chapter_start = start
        heading_path = (
            (current_chapter, heading)
            if current_chapter and current_chapter != heading
            else (heading,)
        )
        candidate_start = (
            current_chapter_start
            if level == 2 and previous_level == 1 and current_chapter_start is not None
            else start
        )
        next_start = (
            heading_positions[index + 1][0]
            if index + 1 < len(heading_positions)
            else len(page.text)
        )
        candidates.append(
            PendingSection(
                title=heading,
                heading_path=heading_path,
                page=page,
                start=candidate_start,
                end=next_start,
            )
        )
        previous_level = level

    sections: list[SourceObject] = []
    used_ids: set[str] = set()
    title_ordinals: dict[str, int] = {}
    for candidate in candidates:
        text = page.text[candidate.start : candidate.end].strip()
        if not section_has_body(text):
            continue
        title_bucket = identity_bucket(candidate.title)
        title_ordinals[title_bucket] = title_ordinals.get(title_bucket, 0) + 1
        section = build_unique_rule_section(
            candidate=candidate,
            book_id=book_id,
            text=text,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata=metadata,
            ordinal=title_ordinals[title_bucket],
            used_ids=used_ids,
        )
        used_ids.add(section.id)
        sections.append(section)
    return tuple(sections)


def extract_structured_objects_from_page(
    *,
    page: SourcePage,
    book_id: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
) -> tuple[SourceObject, ...]:
    lines = page_line_spans(page.text)
    objects: list[SourceObject] = []
    objects.extend(
        extract_tables_from_lines(
            page=page,
            book_id=book_id,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata=metadata,
            lines=lines,
            ordinal_start=1,
        )
    )
    objects.extend(
        extract_stat_profiles_from_lines(
            page=page,
            book_id=book_id,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata=metadata,
            lines=lines,
            ordinal_start=len(objects) + 1,
        )
    )
    objects.extend(
        extract_reference_objects_from_lines(
            page=page,
            book_id=book_id,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata=metadata,
            lines=lines,
            ordinal_start=len(objects) + 1,
        )
    )
    return tuple(objects)


def extract_tables_from_lines(
    *,
    page: SourcePage,
    book_id: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    lines: tuple[LineSpan, ...],
    ordinal_start: int,
) -> tuple[SourceObject, ...]:
    objects: list[SourceObject] = []
    table_ordinal = ordinal_start
    table_row_identity_ordinal = 1
    index = 0
    while index < len(lines):
        if not is_table_line(lines[index].stripped):
            index += 1
            continue
        start_index = index
        while index < len(lines) and is_table_line(lines[index].stripped):
            index += 1
        group = lines[start_index:index]
        data_rows = tuple(line for line in group[1:] if not is_table_separator(line.stripped))
        if not data_rows:
            continue
        title_line = preceding_content_line(lines, start_index)
        title = title_line.stripped if title_line is not None else f"Table {table_ordinal}"
        table_start = title_line.start if title_line is not None else group[0].start
        table_end = group[-1].end
        table_text = page.text[table_start:table_end].strip()
        heading_path = structured_heading_path(lines, start_index, fallback=title)
        table = build_structured_source_object(
            book_id=book_id,
            page=page,
            object_type="table",
            title=title,
            heading_path=heading_path,
            text=table_text,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata={**metadata, "structured_type": "table"},
            ordinal=table_ordinal,
            char_start=table_start,
            char_end=table_end,
            confidence=0.82,
            extraction_method="pipe_table_heuristic",
            search_prefix="table",
        )
        objects.append(table)
        row_ordinal = 1
        for row in data_rows:
            objects.append(
                build_structured_source_object(
                    book_id=book_id,
                    page=page,
                    object_type="table_row",
                    title=f"{title} row {row_ordinal}",
                    heading_path=heading_path,
                    text=row.stripped,
                    text_snapshot_sha256=text_snapshot_sha256,
                    metadata={
                        **metadata,
                        "structured_type": "table_row",
                        "parent_title": title,
                        "row_number": row_ordinal,
                    },
                    ordinal=table_row_identity_ordinal,
                    char_start=row.start,
                    char_end=row.end,
                    confidence=0.76,
                    extraction_method="pipe_table_heuristic",
                    search_prefix="table row",
                    parent_object_id=table.id,
                )
            )
            row_ordinal += 1
            table_row_identity_ordinal += 1
        table_ordinal += 1
    return tuple(objects)


def extract_stat_profiles_from_lines(
    *,
    page: SourcePage,
    book_id: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    lines: tuple[LineSpan, ...],
    ordinal_start: int,
) -> tuple[SourceObject, ...]:
    objects: list[SourceObject] = []
    ordinal = ordinal_start
    index = 0
    while index + 1 < len(lines):
        if not is_stat_header(lines[index].stripped) or not is_stat_value_line(
            lines[index + 1].stripped
        ):
            index += 1
            continue
        title_line = preceding_content_line(lines, index)
        if title_line is None:
            index += 1
            continue
        end_index = index + 2
        while end_index < len(lines) and is_profile_followup_line(lines[end_index].stripped):
            end_index += 1
        profile_start = title_line.start
        profile_end = lines[end_index - 1].end
        profile_text = page.text[profile_start:profile_end].strip()
        stat_text = page.text[lines[index].start : lines[index + 1].end].strip()
        title = title_line.stripped
        heading_path = structured_heading_path(lines, index, fallback=title)
        profile_type = classify_profile_type(title)
        profile = build_structured_source_object(
            book_id=book_id,
            page=page,
            object_type=profile_type,
            title=title,
            heading_path=heading_path,
            text=profile_text,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata={**metadata, "structured_type": profile_type},
            ordinal=ordinal,
            char_start=profile_start,
            char_end=profile_end,
            confidence=0.78,
            extraction_method="stat_profile_heuristic",
            search_prefix=profile_type.replace("_", " "),
        )
        objects.append(profile)
        objects.append(
            build_structured_source_object(
                book_id=book_id,
                page=page,
                object_type="stat_block",
                title=f"{title} Statistics",
                heading_path=heading_path,
                text=stat_text,
                text_snapshot_sha256=text_snapshot_sha256,
                metadata={
                    **metadata,
                    "structured_type": "stat_block",
                    "parent_title": title,
                },
                ordinal=ordinal,
                char_start=lines[index].start,
                char_end=lines[index + 1].end,
                confidence=0.82,
                extraction_method="stat_profile_heuristic",
                search_prefix="stat block statistics profile",
                parent_object_id=profile.id,
            )
        )
        ordinal += 1
        index = end_index
    return tuple(objects)


def extract_reference_objects_from_lines(
    *,
    page: SourcePage,
    book_id: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    lines: tuple[LineSpan, ...],
    ordinal_start: int,
) -> tuple[SourceObject, ...]:
    objects: list[SourceObject] = []
    ordinal = ordinal_start
    context: str | None = None
    for line in lines:
        if not line.stripped:
            continue
        if context == "index" and (match := INDEX_ENTRY_RE.match(line.stripped)):
            title = match.group("title").strip()
            target_page = int(match.group("page"))
            objects.append(
                build_reference_source_object(
                    page=page,
                    book_id=book_id,
                    object_type="index_entry",
                    title=title,
                    heading_path=("Index",),
                    text=line.stripped,
                    text_snapshot_sha256=text_snapshot_sha256,
                    metadata={
                        **metadata,
                        "target_title": title,
                        "target_page": target_page,
                    },
                    ordinal=ordinal,
                    char_start=line.start,
                    char_end=line.end,
                    search_prefix="index entry",
                )
            )
            ordinal += 1
            continue

        if context == "glossary" and (match := GLOSSARY_ENTRY_RE.match(line.stripped)):
            title = match.group("title").strip()
            reference = parse_cross_reference(line.stripped)
            reference_metadata = (
                {
                    "target_title": reference[0],
                    **({"target_page": reference[1]} if reference[1] is not None else {}),
                }
                if reference is not None
                else {}
            )
            objects.append(
                build_reference_source_object(
                    page=page,
                    book_id=book_id,
                    object_type="glossary_entry",
                    title=title,
                    heading_path=("Glossary",),
                    text=line.stripped,
                    text_snapshot_sha256=text_snapshot_sha256,
                    metadata={**metadata, **reference_metadata},
                    ordinal=ordinal,
                    char_start=line.start,
                    char_end=line.end,
                    search_prefix="glossary entry",
                )
            )
            ordinal += 1
            continue

        if is_heading(line.stripped):
            normalized_heading = line.stripped.casefold()
            if normalized_heading == "index":
                context = "index"
                continue
            if normalized_heading == "glossary":
                context = "glossary"
                continue
            context = None

        reference = parse_cross_reference(line.stripped)
        if reference is None:
            continue
        title, target_page = reference
        objects.append(
            build_reference_source_object(
                page=page,
                book_id=book_id,
                object_type="cross_reference",
                title=title,
                heading_path=("Cross References",),
                text=line.stripped,
                text_snapshot_sha256=text_snapshot_sha256,
                metadata={
                    **metadata,
                    "target_title": title,
                    **({"target_page": target_page} if target_page is not None else {}),
                },
                ordinal=ordinal,
                char_start=line.start,
                char_end=line.end,
                search_prefix="cross reference",
            )
        )
        ordinal += 1
    return tuple(objects)


def build_reference_source_object(
    *,
    page: SourcePage,
    book_id: str,
    object_type: str,
    title: str,
    heading_path: tuple[str, ...],
    text: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    ordinal: int,
    char_start: int,
    char_end: int,
    search_prefix: str,
) -> SourceObject:
    return build_structured_source_object(
        page=page,
        book_id=book_id,
        object_type=object_type,
        title=title,
        heading_path=heading_path,
        text=text,
        text_snapshot_sha256=text_snapshot_sha256,
        metadata={**metadata, "structured_type": object_type},
        ordinal=ordinal,
        char_start=char_start,
        char_end=char_end,
        confidence=0.72,
        extraction_method=f"{object_type}_heuristic",
        search_prefix=search_prefix,
    )


def build_structured_source_object(
    *,
    page: SourcePage,
    book_id: str,
    object_type: str,
    title: str,
    heading_path: tuple[str, ...],
    text: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    ordinal: int,
    char_start: int,
    char_end: int,
    confidence: float,
    extraction_method: str,
    search_prefix: str,
    parent_object_id: str | None = None,
) -> SourceObject:
    return SourceObject(
        id=deterministic_source_object_id(
            book_id=book_id,
            page_start=page.page_number,
            page_end=page.page_number,
            object_type=object_type,
            ordinal=ordinal,
            text=text,
        ),
        book_id=book_id,
        page_id=page.page_id,
        object_type=object_type,
        parent_object_id=parent_object_id,
        title=title,
        heading_path=heading_path,
        page_start=page.page_number,
        page_end=page.page_number,
        char_start=char_start,
        char_end=char_end,
        text=text,
        search_text=search_text(
            title,
            heading_path,
            f"{search_prefix} {text}",
        ),
        metadata_json=json.dumps(metadata, sort_keys=True),
        confidence=confidence,
        extraction_method=extraction_method,
        text_snapshot_sha256=text_snapshot_sha256,
    )


def heading_lines(text: str) -> tuple[tuple[int, int, str], ...]:
    positions: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        line_start = offset + line.find(stripped) if stripped else offset
        line_end = line_start + len(stripped)
        if is_heading(stripped):
            positions.append((line_start, line_end, stripped))
        offset += len(line)
    return tuple(positions)


def is_heading(line: str) -> bool:
    if not 3 <= len(line) <= 80:
        return False
    if line.endswith((".", ",", ";", ":")) and not HEADING_RE.match(line):
        return False
    if HEADING_RE.match(line):
        return True
    words = line.split()
    if len(words) > 8:
        return False
    letters = [character for character in line if character.isalpha()]
    if not letters:
        return False
    if line.isupper():
        return True
    return all(word[:1].isupper() for word in words if word[:1].isalpha())


def heading_level(heading: str) -> int:
    return 1 if HEADING_RE.match(heading) else 2


def section_has_body(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) > 1


def identity_bucket(value: str) -> str:
    return " ".join(value.casefold().split())


def page_line_spans(text: str) -> tuple[LineSpan, ...]:
    lines: list[LineSpan] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        start = offset + line.find(stripped) if stripped else offset
        end = start + len(stripped)
        lines.append(LineSpan(text=line, stripped=stripped, start=start, end=end))
        offset += len(line)
    return tuple(lines)


def is_table_line(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 3


def is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    return bool(cells) and all(set(cell) <= {"-", ":", " "} for cell in cells)


def preceding_content_line(
    lines: tuple[LineSpan, ...],
    before_index: int,
) -> LineSpan | None:
    for index in range(before_index - 1, -1, -1):
        line = lines[index]
        if not line.stripped:
            continue
        if is_table_line(line.stripped):
            continue
        if is_stat_header(line.stripped):
            continue
        return line
    return None


def structured_heading_path(
    lines: tuple[LineSpan, ...],
    before_index: int,
    *,
    fallback: str,
) -> tuple[str, ...]:
    headings: list[str] = []
    for line in lines[: before_index + 1]:
        if is_heading(line.stripped):
            headings.append(line.stripped)
    if not headings:
        return (fallback,)
    if headings[-1] != fallback and fallback:
        return (*tuple(headings[-2:]), fallback)
    return tuple(headings[-2:])


def is_stat_header(line: str) -> bool:
    tokens = [token.casefold() for token in line.split()]
    matched = [token for token in tokens if token in STAT_HEADER_TOKENS]
    return len(matched) >= 6 and matched == tokens[: len(matched)]


def is_stat_value_line(line: str) -> bool:
    tokens = line.split()
    if len(tokens) < 6:
        return False
    numeric_tokens = [token for token in tokens if token.replace("-", "").isdigit()]
    return len(numeric_tokens) >= 6


def is_profile_followup_line(line: str) -> bool:
    return line.casefold().startswith(PROFILE_FOLLOWUP_PREFIXES)


def classify_profile_type(title: str) -> str:
    lowered = title.casefold()
    if any(marker in lowered for marker in ("creature", "beast", "daemon", "undead")):
        return "monster_profile"
    return "npc_profile"


def parse_cross_reference(line: str) -> tuple[str, int | None] | None:
    match = CROSS_REFERENCE_RE.search(line)
    if match is None:
        return None
    title = match.group("title").strip()
    target_page = match.group("page")
    return title, int(target_page) if target_page is not None else None


def build_rule_section(
    *,
    candidate: PendingSection,
    book_id: str,
    text: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    ordinal: int,
) -> SourceObject:
    confidence = min(0.74, 0.68) if metadata["ocr_layout_available"] is False else 0.74
    return SourceObject(
        id=deterministic_source_object_id(
            book_id=book_id,
            page_start=candidate.page.page_number,
            page_end=candidate.page.page_number,
            object_type="rule_section",
            ordinal=ordinal,
            text=text,
        ),
        book_id=book_id,
        page_id=candidate.page.page_id,
        object_type="rule_section",
        title=candidate.title,
        heading_path=candidate.heading_path,
        page_start=candidate.page.page_number,
        page_end=candidate.page.page_number,
        char_start=candidate.start,
        char_end=candidate.end,
        text=text,
        search_text=search_text(candidate.title, candidate.heading_path, text),
        metadata_json=json.dumps(metadata, sort_keys=True),
        confidence=confidence,
        extraction_method="heading_heuristic",
        text_snapshot_sha256=text_snapshot_sha256,
    )


def build_unique_rule_section(
    *,
    candidate: PendingSection,
    book_id: str,
    text: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    ordinal: int,
    used_ids: set[str],
) -> SourceObject:
    while True:
        section = build_rule_section(
            candidate=candidate,
            book_id=book_id,
            text=text,
            text_snapshot_sha256=text_snapshot_sha256,
            metadata=metadata,
            ordinal=ordinal,
        )
        if section.id not in used_ids:
            return section
        ordinal += 1


def build_page_chunks(
    *,
    page: SourcePage,
    book_id: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    covered_spans: tuple[tuple[int, int], ...],
) -> tuple[SourceObject, ...]:
    chunks: list[SourceObject] = []
    ordinal = 1
    for start, end in uncovered_spans(len(page.text), covered_spans):
        text = page.text[start:end].strip()
        if not text:
            continue
        chunks.append(
            build_page_chunk(
                page=page,
                book_id=book_id,
                text_snapshot_sha256=text_snapshot_sha256,
                metadata=metadata,
                ordinal=ordinal,
                char_start=start,
                char_end=end,
                text=text,
            )
        )
        ordinal += 1
    return tuple(chunks)


def build_page_chunk(
    *,
    page: SourcePage,
    book_id: str,
    text_snapshot_sha256: str,
    metadata: dict[str, object],
    ordinal: int,
    char_start: int,
    char_end: int,
    text: str,
) -> SourceObject:
    confidence = 0.45 if metadata["ocr_layout_available"] is False else 0.55
    return SourceObject(
        id=deterministic_source_object_id(
            book_id=book_id,
            page_start=page.page_number,
            page_end=page.page_number,
            object_type="page_chunk",
            ordinal=ordinal,
            text=text,
        ),
        book_id=book_id,
        page_id=page.page_id,
        object_type="page_chunk",
        title=f"Page {page.page_number}",
        heading_path=(f"Page {page.page_number}",),
        page_start=page.page_number,
        page_end=page.page_number,
        char_start=char_start,
        char_end=char_end,
        text=text,
        search_text=search_text(f"Page {page.page_number}", (f"Page {page.page_number}",), text),
        metadata_json=json.dumps(metadata, sort_keys=True),
        confidence=confidence,
        extraction_method="page_chunk_fallback",
        text_snapshot_sha256=text_snapshot_sha256,
    )


def page_metadata(
    page: SourcePage,
    layout_page: LayoutPage | None,
) -> dict[str, object]:
    ocr_derived = page.extraction_method.lower().startswith("ocr")
    has_word_geometry = bool(layout_page and layout_page.has_word_geometry)
    return {
        "layout_available": layout_page is not None,
        "ocr_derived": ocr_derived,
        "ocr_layout_available": (not ocr_derived) or has_word_geometry,
        "word_geometry_available": has_word_geometry,
    }


def search_text(title: str, heading_path: tuple[str, ...], text: str) -> str:
    parts = [title, *heading_path, text]
    return " ".join(part.strip() for part in parts if part.strip())


def uncovered_spans(
    text_length: int,
    covered_spans: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    if not covered_spans:
        return ((0, text_length),)

    spans: list[tuple[int, int]] = []
    cursor = 0
    for start, end in sorted(covered_spans):
        bounded_start = max(0, min(start, text_length))
        bounded_end = max(bounded_start, min(end, text_length))
        if cursor < bounded_start:
            spans.append((cursor, bounded_start))
        cursor = max(cursor, bounded_end)
    if cursor < text_length:
        spans.append((cursor, text_length))
    return tuple(spans)

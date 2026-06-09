import { useMemo, useState } from "react";

import type { ApiClient } from "../../lib/apiClient";
import { apiClient } from "../../lib/apiClient";
import { errorMessage } from "../../lib/apiError";
import {
  groupByCategory,
  mergeLibraryRows,
  type LibraryBookRow,
} from "../../lib/grouping";
import type {
  BookSummaryResponse,
  RetrievalStatusResponse,
  SourceSetBookResponse,
} from "../../types/api";
import { BookCategorySection } from "./BookCategorySection";

const VECTOR_STATUS_LABELS: Record<string, string> = {
  disabled: "disabled",
  failed: "failed",
  indexed: "indexed",
  indexing: "indexing",
  needs_refresh: "needs rebuild",
  not_started: "not indexed",
};

const VECTOR_STATUS_ORDER = [
  "indexed",
  "needs_refresh",
  "not_started",
  "indexing",
  "failed",
  "disabled",
];

export type LibraryTabProps = {
  activeSourceSetId: string | null;
  books: BookSummaryResponse[];
  client?: ApiClient;
  collapsedCategories: string[];
  onOpenBook: (book: LibraryBookRow) => void;
  onSourceSetBookUpdated: (book: SourceSetBookResponse) => void;
  onToggleCategory: (category: string) => void;
  retrievalStatus?: RetrievalStatusResponse | null;
  sourceSetBooks: SourceSetBookResponse[];
};

export function LibraryTab({
  activeSourceSetId,
  books,
  client = apiClient,
  collapsedCategories,
  onOpenBook,
  onSourceSetBookUpdated,
  onToggleCategory,
  retrievalStatus = null,
  sourceSetBooks,
}: LibraryTabProps) {
  const [filter, setFilter] = useState("");
  const [savingBookIds, setSavingBookIds] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});

  const rows = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const merged = mergeLibraryRows(books, sourceSetBooks);
    if (!needle) {
      return merged;
    }
    return merged.filter(
      (book) =>
        book.title.toLowerCase().includes(needle) ||
        book.category.toLowerCase().includes(needle),
    );
  }, [books, filter, sourceSetBooks]);
  const semanticStatus = useMemo(
    () =>
      retrievalStatus
        ? aggregateRetrievalStatus(retrievalStatus)
        : semanticSearchStatus(books),
    [books, retrievalStatus],
  );

  async function handleToggle(book: LibraryBookRow, enabled: boolean) {
    if (activeSourceSetId === null) {
      setErrors((previous) => ({
        ...previous,
        [book.book_id]: "No active source set.",
      }));
      return;
    }
    setSavingBookIds((previous) => new Set(previous).add(book.book_id));
    setErrors((previous) => ({ ...previous, [book.book_id]: "" }));
    try {
      const updated = await client.setSourceSetBook(
        activeSourceSetId,
        book.book_id,
        enabled,
      );
      onSourceSetBookUpdated(updated);
    } catch (error) {
      setErrors((previous) => ({
        ...previous,
        [book.book_id]: errorMessage(error),
      }));
    } finally {
      setSavingBookIds((previous) => {
        const next = new Set(previous);
        next.delete(book.book_id);
        return next;
      });
    }
  }

  return (
    <div className="library-tab">
      <input
        aria-label="Filter library books"
        onChange={(event) => setFilter(event.currentTarget.value)}
        placeholder="Filter library books..."
        type="search"
        value={filter}
      />
      <div
        aria-label="Semantic search status"
        className="library-tab__semantic-status"
      >
        {semanticStatus}
      </div>
      <div className="library-tab__list">
        {groupByCategory(rows).map((group) => (
          <BookCategorySection
            books={group.books}
            category={group.category}
            collapsed={collapsedCategories.includes(group.category)}
            errors={errors}
            key={group.category}
            onOpen={onOpenBook}
            onToggle={handleToggle}
            onToggleCategory={onToggleCategory}
            savingBookIds={savingBookIds}
          />
        ))}
      </div>
    </div>
  );
}

function semanticSearchStatus(books: BookSummaryResponse[]) {
  const counts = new Map<string, number>();
  for (const book of books) {
    const status = book.vector_status || "disabled";
    counts.set(status, (counts.get(status) ?? 0) + 1);
  }
  const orderedStatuses = [
    ...VECTOR_STATUS_ORDER,
    ...[...counts.keys()].filter((status) => !VECTOR_STATUS_ORDER.includes(status)),
  ];
  const parts = orderedStatuses.flatMap((status) => {
    const count = counts.get(status) ?? 0;
    if (count === 0) {
      return [];
    }
    return `${count} ${VECTOR_STATUS_LABELS[status] ?? status.replace(/_/g, " ")}`;
  });
  return `Semantic search: ${parts.length ? parts.join(", ") : "0 indexed"}`;
}

function aggregateRetrievalStatus(status: RetrievalStatusResponse) {
  return (
    `Retrieval: ${status.books_enabled} enabled, ` +
    `${status.page_text_indexed} page text indexed, ` +
    `${status.source_objects_indexed} source-object indexed, ` +
    `${status.table_or_stat_indexed} table/stat indexed, ` +
    `${status.vectorized_enabled} vectorized enabled, ` +
    `vector ${status.vector_status}`
  );
}

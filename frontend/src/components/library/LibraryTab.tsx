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
  SourceSetBookResponse,
} from "../../types/api";
import { BookCategorySection } from "./BookCategorySection";

export type LibraryTabProps = {
  activeSourceSetId: string | null;
  books: BookSummaryResponse[];
  client?: ApiClient;
  collapsedCategories: string[];
  onOpenBook: (book: LibraryBookRow) => void;
  onSourceSetBookUpdated: (book: SourceSetBookResponse) => void;
  onToggleCategory: (category: string) => void;
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

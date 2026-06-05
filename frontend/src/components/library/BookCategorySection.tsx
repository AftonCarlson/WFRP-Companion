import { useEffect, useRef } from "react";

import { ChevronDown, ChevronRight } from "lucide-react";

import type { LibraryBookRow } from "../../lib/grouping";
import { BookRow } from "./BookRow";

export type BookCategorySectionProps = {
  books: LibraryBookRow[];
  category: string;
  collapsed: boolean;
  errors: Record<string, string>;
  onOpen: (book: LibraryBookRow) => void;
  onToggle: (book: LibraryBookRow, enabled: boolean) => Promise<void> | void;
  onToggleCategory: (category: string) => void;
  savingBookIds: Set<string>;
};

export function BookCategorySection({
  books,
  category,
  collapsed,
  errors,
  onOpen,
  onToggle,
  onToggleCategory,
  savingBookIds,
}: BookCategorySectionProps) {
  const categoryCheckboxRef = useRef<HTMLInputElement>(null);
  const allEnabled = books.length > 0 && books.every((book) => book.enabled);
  const someEnabled = books.some((book) => book.enabled);
  const hasSavingBook = books.some((book) => savingBookIds.has(book.book_id));

  useEffect(() => {
    if (categoryCheckboxRef.current) {
      categoryCheckboxRef.current.indeterminate = someEnabled && !allEnabled;
    }
  }, [allEnabled, someEnabled]);

  function handleCategoryToggle(enabled: boolean) {
    books
      .filter((book) => book.enabled !== enabled)
      .forEach((book) => {
        void onToggle(book, enabled);
      });
  }

  return (
    <section className="book-category">
      <div className="book-category__summary">
        <button
          aria-label={`${collapsed ? "Expand" : "Collapse"} ${category}`}
          className="book-category__collapse"
          onClick={() => onToggleCategory(category)}
          type="button"
        >
          {collapsed ? (
            <ChevronRight aria-hidden="true" size={15} />
          ) : (
            <ChevronDown aria-hidden="true" size={15} />
          )}
        </button>
        <input
          aria-label={`Select all books in ${category}`}
          checked={allEnabled}
          disabled={books.length === 0 || hasSavingBook}
          onChange={(event) => handleCategoryToggle(event.currentTarget.checked)}
          ref={categoryCheckboxRef}
          type="checkbox"
        />
        <span>{category}</span>
        <small>{books.length}</small>
      </div>
      {collapsed ? null : (
        <div className="book-category__books">
          {books.map((book) => (
            <BookRow
              book={book}
              error={errors[book.book_id]}
              key={book.book_id}
              onOpen={onOpen}
              onToggle={onToggle}
              saving={savingBookIds.has(book.book_id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

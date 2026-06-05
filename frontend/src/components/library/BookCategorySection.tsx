import { ChevronDown, ChevronRight } from "lucide-react";

import type { LibraryBookRow } from "../../lib/grouping";
import { BookRow } from "./BookRow";

export type BookCategorySectionProps = {
  books: LibraryBookRow[];
  category: string;
  collapsed: boolean;
  errors: Record<string, string>;
  onOpen: (book: LibraryBookRow) => void;
  onToggle: (book: LibraryBookRow, enabled: boolean) => void;
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
  return (
    <section className="book-category">
      <button
        className="book-category__summary"
        onClick={() => onToggleCategory(category)}
        type="button"
      >
        {collapsed ? (
          <ChevronRight aria-hidden="true" size={15} />
        ) : (
          <ChevronDown aria-hidden="true" size={15} />
        )}
        <span>{category}</span>
        <small>{books.length}</small>
      </button>
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

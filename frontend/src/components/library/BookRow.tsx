import type { LibraryBookRow } from "../../lib/grouping";

export type BookRowProps = {
  book: LibraryBookRow;
  error?: string;
  onOpen: (book: LibraryBookRow) => void;
  onToggle: (book: LibraryBookRow, enabled: boolean) => void;
  saving?: boolean;
};

export function BookRow({ book, error, onOpen, onToggle, saving }: BookRowProps) {
  const status = book.needs_attention
    ? "needs attention"
    : book.search_ready
      ? "ready"
      : "not indexed";

  return (
    <div className="book-row">
      <label>
        <input
          checked={book.enabled}
          disabled={saving}
          onChange={(event) => onToggle(book, event.currentTarget.checked)}
          type="checkbox"
        />
        <span>
          {book.title}
          <small>{status}</small>
        </span>
      </label>
      <button
        aria-label={`Open ${book.title}`}
        disabled={!book.reader_ready}
        onClick={() => onOpen(book)}
        type="button"
      >
        Open
      </button>
      {error ? <div className="book-row__error">{error}</div> : null}
    </div>
  );
}

import type { ApiClient } from "../../lib/apiClient";
import type { LibraryBookRow } from "../../lib/grouping";
import type {
  BookSummaryResponse,
  SearchHitResponse,
  SourceSetBookResponse,
} from "../../types/api";
import type { LeftTab, PdfViewMode } from "../../state/workspaceState";
import { LibraryTab } from "./LibraryTab";
import { SearchTab } from "./SearchTab";
import "./LibrarySearchPanel.css";

export type LibrarySearchPanelProps = {
  activeSourceSetId: string | null;
  books: BookSummaryResponse[];
  client?: ApiClient;
  collapsedCategories: string[];
  leftTab: LeftTab;
  onOpenPdfPage: (input: {
    bookId: string;
    title: string;
    pageNumber: number;
    viewMode?: PdfViewMode;
  }) => void;
  onSetLeftTab: (leftTab: LeftTab) => void;
  onSourceSetBookUpdated: (book: SourceSetBookResponse) => void;
  onToggleCategory: (category: string) => void;
  sourceSetBooks: SourceSetBookResponse[];
};

export function LibrarySearchPanel({
  activeSourceSetId,
  books,
  client,
  collapsedCategories,
  leftTab,
  onOpenPdfPage,
  onSetLeftTab,
  onSourceSetBookUpdated,
  onToggleCategory,
  sourceSetBooks,
}: LibrarySearchPanelProps) {
  function handleOpenBook(book: LibraryBookRow) {
    onOpenPdfPage({
      bookId: book.book_id,
      title: book.title,
      pageNumber: 1,
    });
  }

  function handleOpenHit(hit: SearchHitResponse) {
    onOpenPdfPage({
      bookId: hit.book_id,
      title: hit.title,
      pageNumber: hit.pdf_page_number,
      viewMode: "single",
    });
  }

  return (
    <div className="library-search-panel">
      <div className="library-search-panel__tabs" role="tablist">
        <button
          aria-controls="library-tab-panel"
          aria-selected={leftTab === "library"}
          id="library-tab"
          onClick={() => onSetLeftTab("library")}
          role="tab"
          tabIndex={leftTab === "library" ? 0 : -1}
          type="button"
        >
          Library
        </button>
        <button
          aria-controls="search-tab-panel"
          aria-selected={leftTab === "search"}
          id="search-tab"
          onClick={() => onSetLeftTab("search")}
          role="tab"
          tabIndex={leftTab === "search" ? 0 : -1}
          type="button"
        >
          Search
        </button>
      </div>
      {leftTab === "library" ? (
        <div
          aria-labelledby="library-tab"
          id="library-tab-panel"
          role="tabpanel"
        >
          <LibraryTab
            activeSourceSetId={activeSourceSetId}
            books={books}
            client={client}
            collapsedCategories={collapsedCategories}
            onOpenBook={handleOpenBook}
            onSourceSetBookUpdated={onSourceSetBookUpdated}
            onToggleCategory={onToggleCategory}
            sourceSetBooks={sourceSetBooks}
          />
        </div>
      ) : (
        <div aria-labelledby="search-tab" id="search-tab-panel" role="tabpanel">
          <SearchTab client={client} onOpenPdfPage={handleOpenHit} />
        </div>
      )}
    </div>
  );
}

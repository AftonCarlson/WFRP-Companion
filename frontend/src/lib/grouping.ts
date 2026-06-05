import type {
  BookSummaryResponse,
  SearchHitResponse,
  SourceSetBookResponse,
} from "../types/api";

export type LibraryBookRow = SourceSetBookResponse & {
  page_count: number;
  reader_ready: boolean;
  needs_attention: boolean;
};

export type SearchResultGroup = {
  bookId: string;
  title: string;
  category: string;
  hits: SearchHitResponse[];
};

export function mergeLibraryRows(
  books: BookSummaryResponse[],
  sourceSetBooks: SourceSetBookResponse[],
): LibraryBookRow[] {
  const booksById = new Map(books.map((book) => [book.id, book]));
  return sourceSetBooks.map((sourceSetBook) => {
    const book = booksById.get(sourceSetBook.book_id);
    return {
      ...sourceSetBook,
      page_count: book?.page_count ?? 0,
      reader_ready: book?.reader_ready ?? false,
      needs_attention: book?.needs_attention ?? false,
    };
  });
}

export function groupByCategory(rows: LibraryBookRow[]) {
  const groups = new Map<string, LibraryBookRow[]>();
  for (const row of rows) {
    groups.set(row.category, [...(groups.get(row.category) ?? []), row]);
  }
  return [...groups].map(([category, books]) => ({ category, books }));
}

export function groupSearchHits(hits: SearchHitResponse[]): SearchResultGroup[] {
  const groups = new Map<string, SearchResultGroup>();
  for (const hit of hits) {
    const existing = groups.get(hit.book_id);
    if (existing) {
      existing.hits.push(hit);
    } else {
      groups.set(hit.book_id, {
        bookId: hit.book_id,
        title: hit.title,
        category: hit.category,
        hits: [hit],
      });
    }
  }
  return [...groups.values()];
}

export function pdfUrlForBook(bookId: string): string {
  return `/api/books/${encodeURIComponent(bookId)}/pdf`;
}

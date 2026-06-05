import type { PdfViewMode } from "../state/workspaceState";

export function visiblePdfPages(
  pageNumber: number,
  pageCount: number,
  viewMode: PdfViewMode,
): number[] {
  const clampedPage = clampPage(pageNumber, pageCount);
  if (viewMode === "single" || clampedPage <= 2) {
    return [clampedPage];
  }

  const leftPage = clampedPage % 2 === 1 ? clampedPage : clampedPage - 1;
  const pages = [leftPage];
  if (leftPage + 1 <= pageCount) {
    pages.push(leftPage + 1);
  }
  return pages;
}

export function previousPdfPage(
  pageNumber: number,
  pageCount: number,
  viewMode: PdfViewMode,
): number {
  if (viewMode === "single") {
    return clampPage(pageNumber - 1, pageCount);
  }
  const firstVisiblePage = visiblePdfPages(pageNumber, pageCount, viewMode)[0];
  if (firstVisiblePage <= 1) {
    return 1;
  }
  if (firstVisiblePage <= 3) {
    return firstVisiblePage - 1;
  }
  return firstVisiblePage - 2;
}

export function nextPdfPage(
  pageNumber: number,
  pageCount: number,
  viewMode: PdfViewMode,
): number {
  if (viewMode === "single") {
    return clampPage(pageNumber + 1, pageCount);
  }
  const firstVisiblePage = visiblePdfPages(pageNumber, pageCount, viewMode)[0];
  if (firstVisiblePage === 1) {
    return clampPage(2, pageCount);
  }
  if (firstVisiblePage === 2) {
    return clampPage(3, pageCount);
  }
  const nextPage = firstVisiblePage + 2;
  return nextPage > pageCount ? clampPage(pageNumber, pageCount) : nextPage;
}

function clampPage(pageNumber: number, pageCount: number): number {
  return Math.max(1, Math.min(Math.round(pageNumber), Math.max(1, pageCount)));
}

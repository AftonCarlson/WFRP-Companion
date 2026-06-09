import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { ApiClient } from "../../lib/apiClient";
import { renderApp } from "../../test/render";
import { LibrarySearchPanel } from "./LibrarySearchPanel";

const book = {
  id: "core-rules",
  title: "Core Rules",
  category: "Rules / Core",
  relative_path: "Rules/Core.pdf",
  page_count: 10,
  copy_status: "copied",
  text_status: "imported",
  search_status: "indexed",
  visual_status: "not_scanned",
  reader_ready: true,
  search_ready: true,
  fully_ready: false,
  needs_attention: false,
  vector_status: "indexed",
  embedding_provider: "sentence-transformers",
  embedding_dimensions: 1024,
};

const sourceSetBook = {
  source_set_id: "rules-core",
  book_id: "core-rules",
  title: "Core Rules",
  category: "Rules / Core",
  enabled: true,
  search_ready: true,
};

function client(): ApiClient {
  return {
    getHealth: vi.fn(),
    listBooks: vi.fn(),
    getRetrievalStatus: vi.fn(),
    listSourceSets: vi.fn(),
    listSourceSetBooks: vi.fn(),
    setSourceSetBook: vi.fn(),
    searchExact: vi.fn().mockResolvedValue({
      query: "critical hit",
      scope: {
        label: "Rules/Core",
        source_set_id: "rules-core",
        book_ids: ["core-rules"],
        all_books: false,
      },
      hits: [
        {
          rank: 1,
          book_id: "core-rules",
          title: "Core Rules",
          category: "Rules / Core",
          page_id: "core-rules:134",
          page_number: 134,
          pdf_page_number: 134,
          page_label: null,
          snippet: "critical hit",
          score: 1,
        },
      ],
    }),
    getPageText: vi.fn(),
    createChatThread: vi.fn(),
    listChatThreads: vi.fn(),
    getChatThread: vi.fn(),
    sendChatMessage: vi.fn(),
    retryModelRun: vi.fn(),
    streamChatMessage: vi.fn(),
  };
}

it("maps library book opens to page-one PDF requests", async () => {
  const user = userEvent.setup();
  const onOpenPdfPage = vi.fn();

  renderApp(
    <LibrarySearchPanel
      activeSourceSetId="rules-core"
      books={[book]}
      client={client()}
      collapsedCategories={[]}
      leftTab="library"
      onOpenPdfPage={onOpenPdfPage}
      onSetLeftTab={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      retrievalStatus={null}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  await user.click(screen.getByRole("button", { name: "Open Core Rules" }));

  expect(onOpenPdfPage).toHaveBeenCalledWith({
    bookId: "core-rules",
    title: "Core Rules",
    pageNumber: 1,
  });
});

it("maps search result opens to exact page PDF requests", async () => {
  const user = userEvent.setup();
  const onOpenPdfPage = vi.fn();

  renderApp(
    <LibrarySearchPanel
      activeSourceSetId="rules-core"
      books={[book]}
      client={client()}
      collapsedCategories={[]}
      leftTab="search"
      onOpenPdfPage={onOpenPdfPage}
      onSetLeftTab={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      retrievalStatus={null}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  await user.type(screen.getByRole("searchbox", { name: "Search book text" }), "critical hit");
  await user.click(screen.getByRole("button", { name: "Search" }));
  await user.click(
    await screen.findByRole("button", { name: "Open Core Rules PDF page 134" }),
  );

  expect(onOpenPdfPage).toHaveBeenCalledWith({
    bookId: "core-rules",
    title: "Core Rules",
    pageNumber: 134,
    viewMode: "single",
  });
});

it("requests tab changes from the tab buttons", async () => {
  const user = userEvent.setup();
  const onSetLeftTab = vi.fn();

  renderApp(
    <LibrarySearchPanel
      activeSourceSetId="rules-core"
      books={[book]}
      client={client()}
      collapsedCategories={[]}
      leftTab="library"
      onOpenPdfPage={vi.fn()}
      onSetLeftTab={onSetLeftTab}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      retrievalStatus={null}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  await user.click(screen.getByRole("tab", { name: "Search" }));

  expect(onSetLeftTab).toHaveBeenCalledWith("search");
});

it("requests a return to the library tab from search", async () => {
  const user = userEvent.setup();
  const onSetLeftTab = vi.fn();

  renderApp(
    <LibrarySearchPanel
      activeSourceSetId="rules-core"
      books={[book]}
      client={client()}
      collapsedCategories={[]}
      leftTab="search"
      onOpenPdfPage={vi.fn()}
      onSetLeftTab={onSetLeftTab}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      retrievalStatus={null}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  await user.click(screen.getByRole("tab", { name: "Library" }));

  expect(onSetLeftTab).toHaveBeenCalledWith("library");
});

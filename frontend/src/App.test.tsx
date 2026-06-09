import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";

import { apiClient } from "./lib/apiClient";
import App from "./App";
import { renderApp } from "./test/render";

vi.mock("./components/pdf/PdfCanvas", () => ({
  PdfCanvas: () => <div data-testid="pdf-canvas">PDF canvas</div>,
}));

beforeEach(() => {
  vi.spyOn(apiClient, "getHealth").mockResolvedValue({
    status: "ok",
    database: "ready",
  });
  vi.spyOn(apiClient, "listBooks").mockResolvedValue({
    books: [
      {
        id: "core-rules",
        title: "Core Rules",
        category: "Rules / Core",
        relative_path: "Rules/Core/Core Rules.pdf",
        page_count: 256,
        copy_status: "copied",
        text_status: "imported",
        search_status: "indexed",
        visual_status: "pending",
        reader_ready: true,
        search_ready: true,
        fully_ready: false,
        needs_attention: false,
        vector_status: "indexed",
        embedding_provider: "sentence-transformers",
        embedding_dimensions: 1024,
      },
      {
        id: "bestiary",
        title: "Old World Bestiary",
        category: "Creatures",
        relative_path: "Creatures/Old World Bestiary.pdf",
        page_count: 128,
        copy_status: "copied",
        text_status: "imported",
        search_status: "indexed",
        visual_status: "pending",
        reader_ready: true,
        search_ready: true,
        fully_ready: false,
        needs_attention: false,
        vector_status: "disabled",
        embedding_provider: null,
        embedding_dimensions: null,
      },
    ],
  });
  vi.spyOn(apiClient, "getRetrievalStatus").mockResolvedValue({
    books_total: 2,
    books_enabled: 1,
    page_text_indexed: 2,
    source_objects_indexed: 2,
    table_or_stat_indexed: 1,
    vectorized_current: 1,
    vectorized_enabled: 1,
    embedding_provider: "sentence-transformers",
    embedding_dimensions: 1024,
    vector_status: "ready",
  });
  vi.spyOn(apiClient, "listSourceSets").mockResolvedValue({
    active_source_set_id: "rules-core",
    source_sets: [
      {
        id: "rules-core",
        name: "Rules/Core",
        description: null,
        is_builtin: true,
        active: true,
      },
    ],
  });
  vi.spyOn(apiClient, "listSourceSetBooks").mockResolvedValue({
    source_set_id: "rules-core",
    books: [
      {
        source_set_id: "rules-core",
        book_id: "core-rules",
        title: "Core Rules",
        category: "Rules / Core",
        enabled: true,
        search_ready: true,
      },
      {
        source_set_id: "rules-core",
        book_id: "bestiary",
        title: "Old World Bestiary",
        category: "Creatures",
        enabled: false,
        search_ready: true,
      },
    ],
  });
  vi.spyOn(apiClient, "setSourceSetBook").mockResolvedValue({
    source_set_id: "rules-core",
    book_id: "core-rules",
    title: "Core Rules",
    category: "Rules / Core",
    enabled: false,
    search_ready: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

it("renders the first WFRP Companion workspace shell", async () => {
  renderApp(<App />);

  expect(
    screen.getByRole("main", { name: "WFRP Companion workspace" }),
  ).toBeInTheDocument();
  expect(await screen.findByText("Core Rules")).toBeInTheDocument();
  expect(screen.getByText("1 books enabled")).toBeInTheDocument();
  expect(
    screen.getByText("Open a source from Library or Search."),
  ).toBeInTheDocument();
  expect(screen.getByRole("log", { name: "Agent transcript" })).toBeInTheDocument();
});

it("opens a PDF tab from the library", async () => {
  const user = userEvent.setup();
  renderApp(<App />);

  await user.click(await screen.findByRole("button", { name: "Open Core Rules" }));

  expect(
    screen.getByRole("tab", { name: "Core Rules" }),
  ).toBeInTheDocument();
  expect(screen.getByTestId("pdf-canvas")).toBeInTheDocument();
});

it("reconciles enabled book count after a checkbox update", async () => {
  const user = userEvent.setup();
  renderApp(<App />);

  await user.click(await screen.findByRole("checkbox", { name: /Core Rules/i }));

  expect(await screen.findByText("0 books enabled")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Old World Bestiary/i })).not.toBeChecked();
});

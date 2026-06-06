import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { ApiClient } from "../../lib/apiClient";
import { renderApp } from "../../test/render";
import { LibraryTab } from "./LibraryTab";

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
};

const sourceSetBook = {
  source_set_id: "rules-core",
  book_id: "core-rules",
  title: "Core Rules",
  category: "Rules / Core",
  enabled: true,
  search_ready: true,
};

const attentionBook = {
  ...book,
  id: "attention-book",
  title: "Attention Book",
  needs_attention: true,
  reader_ready: false,
  search_ready: false,
};

const attentionSourceSetBook = {
  ...sourceSetBook,
  book_id: "attention-book",
  title: "Attention Book",
  enabled: false,
  search_ready: false,
};

const unindexedBook = {
  ...book,
  id: "unindexed-book",
  title: "Unindexed Book",
  search_ready: false,
};

const unindexedSourceSetBook = {
  ...sourceSetBook,
  book_id: "unindexed-book",
  title: "Unindexed Book",
  enabled: false,
  search_ready: false,
};

function client(overrides: Partial<ApiClient> = {}) {
  return {
    setSourceSetBook: vi.fn().mockResolvedValue({
      ...sourceSetBook,
      enabled: false,
    }),
    getHealth: vi.fn(),
    listBooks: vi.fn(),
    listSourceSets: vi.fn(),
    listSourceSetBooks: vi.fn(),
    searchExact: vi.fn(),
    getPageText: vi.fn(),
    ...overrides,
  } as ApiClient;
}

it("renders grouped checkbox rows and opens books", async () => {
  const user = userEvent.setup();
  const onOpenBook = vi.fn();

  renderApp(
    <LibraryTab
      activeSourceSetId="rules-core"
      books={[book]}
      client={client()}
      collapsedCategories={[]}
      onOpenBook={onOpenBook}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  expect(screen.getByRole("button", { name: /Rules \/ Core/i })).toBeInTheDocument();
  expect(screen.queryByText("Open")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Open Core Rules" }));

  expect(onOpenBook).toHaveBeenCalledWith(expect.objectContaining({ book_id: "core-rules" }));
});

it("persists checkbox changes through the source-set API", async () => {
  const user = userEvent.setup();
  const fakeClient = client();
  const onUpdated = vi.fn();

  renderApp(
    <LibraryTab
      activeSourceSetId="rules-core"
      books={[book]}
      client={fakeClient}
      collapsedCategories={[]}
      onOpenBook={vi.fn()}
      onSourceSetBookUpdated={onUpdated}
      onToggleCategory={vi.fn()}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  await user.click(screen.getByRole("checkbox", { name: /Core Rules/i }));

  await waitFor(() =>
    expect(fakeClient.setSourceSetBook).toHaveBeenCalledWith(
      "rules-core",
      "core-rules",
      false,
    ),
  );
  expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
});

it("reports checkbox API failures without changing source-of-truth locally", async () => {
  const user = userEvent.setup();

  renderApp(
    <LibraryTab
      activeSourceSetId="rules-core"
      books={[book]}
      client={client({
        setSourceSetBook: vi.fn().mockRejectedValue(new Error("Nope")),
      })}
      collapsedCategories={[]}
      onOpenBook={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  await user.click(screen.getByRole("checkbox", { name: /Core Rules/i }));

  expect(await screen.findByText("Nope")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Core Rules/i })).toBeChecked();
});

it("reports missing active source set before attempting checkbox writes", async () => {
  const user = userEvent.setup();
  const fakeClient = client();

  renderApp(
    <LibraryTab
      activeSourceSetId={null}
      books={[book]}
      client={fakeClient}
      collapsedCategories={[]}
      onOpenBook={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  await user.click(screen.getByRole("checkbox", { name: /Core Rules/i }));

  expect(await screen.findByText("No active source set.")).toBeInTheDocument();
  expect(fakeClient.setSourceSetBook).not.toHaveBeenCalled();
});

it("filters books and renders attention and disabled reader states", async () => {
  const user = userEvent.setup();

  renderApp(
    <LibraryTab
      activeSourceSetId="rules-core"
      books={[book, attentionBook]}
      client={client()}
      collapsedCategories={[]}
      onOpenBook={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      sourceSetBooks={[sourceSetBook, attentionSourceSetBook]}
    />,
  );

  expect(screen.getByRole("button", { name: "Open Attention Book" })).toBeDisabled();

  await user.type(screen.getByRole("searchbox", { name: "Filter library books" }), "attention");

  expect(screen.queryByText("Core Rules")).not.toBeInTheDocument();
  expect(screen.getByText("Attention Book")).toBeInTheDocument();
});

it("does not render per-book readiness labels", () => {
  renderApp(
    <LibraryTab
      activeSourceSetId="rules-core"
      books={[book, attentionBook, unindexedBook]}
      client={client()}
      collapsedCategories={[]}
      onOpenBook={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      sourceSetBooks={[sourceSetBook, attentionSourceSetBook, unindexedSourceSetBook]}
    />,
  );

  expect(screen.queryByText("ready")).not.toBeInTheDocument();
  expect(screen.queryByText("needs attention")).not.toBeInTheDocument();
  expect(screen.queryByText("not indexed")).not.toBeInTheDocument();
});

it("enables every unchecked book in a category from the section checkbox", async () => {
  const user = userEvent.setup();
  const fakeClient = client({
    setSourceSetBook: vi.fn().mockImplementation((sourceSetId, bookId, enabled) =>
      Promise.resolve({
        ...sourceSetBook,
        source_set_id: sourceSetId,
        book_id: bookId,
        enabled,
      }),
    ),
  });

  renderApp(
    <LibraryTab
      activeSourceSetId="rules-core"
      books={[book, unindexedBook]}
      client={fakeClient}
      collapsedCategories={[]}
      onOpenBook={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      sourceSetBooks={[sourceSetBook, unindexedSourceSetBook]}
    />,
  );

  const categoryCheckbox = screen.getByRole("checkbox", {
    name: "Select all books in Rules / Core",
  }) as HTMLInputElement;
  expect(categoryCheckbox).not.toBeChecked();
  expect(categoryCheckbox.indeterminate).toBe(true);

  await user.click(categoryCheckbox);

  await waitFor(() =>
    expect(fakeClient.setSourceSetBook).toHaveBeenCalledWith(
      "rules-core",
      "unindexed-book",
      true,
    ),
  );
  expect(fakeClient.setSourceSetBook).toHaveBeenCalledTimes(1);
});

it("disables every checked book in a category from the section checkbox", async () => {
  const user = userEvent.setup();
  const fakeClient = client({
    setSourceSetBook: vi.fn().mockImplementation((sourceSetId, bookId, enabled) =>
      Promise.resolve({
        ...sourceSetBook,
        source_set_id: sourceSetId,
        book_id: bookId,
        enabled,
      }),
    ),
  });

  renderApp(
    <LibraryTab
      activeSourceSetId="rules-core"
      books={[book, unindexedBook]}
      client={fakeClient}
      collapsedCategories={[]}
      onOpenBook={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={vi.fn()}
      sourceSetBooks={[
        sourceSetBook,
        {
          ...unindexedSourceSetBook,
          enabled: true,
        },
      ]}
    />,
  );

  const categoryCheckbox = screen.getByRole("checkbox", {
    name: "Select all books in Rules / Core",
  });
  expect(categoryCheckbox).toBeChecked();

  await user.click(categoryCheckbox);

  await waitFor(() =>
    expect(fakeClient.setSourceSetBook).toHaveBeenCalledWith(
      "rules-core",
      "core-rules",
      false,
    ),
  );
  expect(fakeClient.setSourceSetBook).toHaveBeenCalledWith(
    "rules-core",
    "unindexed-book",
    false,
  );
  expect(fakeClient.setSourceSetBook).toHaveBeenCalledTimes(2);
});

it("honors collapsed library categories", () => {
  const onToggleCategory = vi.fn();

  renderApp(
    <LibraryTab
      activeSourceSetId="rules-core"
      books={[book]}
      client={client()}
      collapsedCategories={["Rules / Core"]}
      onOpenBook={vi.fn()}
      onSourceSetBookUpdated={vi.fn()}
      onToggleCategory={onToggleCategory}
      sourceSetBooks={[sourceSetBook]}
    />,
  );

  expect(screen.queryByText("Core Rules")).not.toBeInTheDocument();
  screen.getByRole("button", { name: /Rules \/ Core/i }).click();

  expect(onToggleCategory).toHaveBeenCalledWith("Rules / Core");
});

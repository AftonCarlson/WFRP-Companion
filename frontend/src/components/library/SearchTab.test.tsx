import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { ApiClient } from "../../lib/apiClient";
import { renderApp } from "../../test/render";
import { SearchTab } from "./SearchTab";

function client(overrides: Partial<ApiClient> = {}) {
  return {
    searchExact: vi.fn().mockResolvedValue({
      query: "critical hit",
      scope: {
        label: "active_source_set",
        source_set_id: "rules-core",
        book_ids: ["core-rules"],
        all_books: false,
      },
      hits: [
        {
          rank: 1,
          book_id: "core-rules",
          title: "Core Rules",
          category: "Rules",
          page_id: "core-rules:134",
          page_number: 134,
          snippet: "...critical hit...",
          score: -1,
        },
      ],
    }),
    getPageText: vi.fn().mockResolvedValue({
      page_id: "core-rules:134",
      book_id: "core-rules",
      page_number: 134,
      page_label: null,
      text: "Full critical hit page text.",
      text_chars: 28,
    }),
    getHealth: vi.fn(),
    listBooks: vi.fn(),
    listSourceSets: vi.fn(),
    listSourceSetBooks: vi.fn(),
    setSourceSetBook: vi.fn(),
    ...overrides,
  } as ApiClient;
}

it("searches exact text and opens PDF pages from results", async () => {
  const user = userEvent.setup();
  const fakeClient = client();
  const onOpenPdfPage = vi.fn();

  renderApp(<SearchTab client={fakeClient} onOpenPdfPage={onOpenPdfPage} />);

  await user.type(screen.getByRole("searchbox", { name: "Search book text" }), "critical hit");
  await user.click(screen.getByRole("button", { name: "Search" }));

  expect(await screen.findByText("...critical hit...")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Open PDF page" }));

  expect(onOpenPdfPage).toHaveBeenCalledWith(
    expect.objectContaining({ book_id: "core-rules", page_number: 134 }),
  );
});

it("loads full page text only when requested", async () => {
  const user = userEvent.setup();
  const fakeClient = client();

  renderApp(<SearchTab client={fakeClient} onOpenPdfPage={vi.fn()} />);

  await user.type(screen.getByRole("searchbox", { name: "Search book text" }), "critical hit");
  await user.click(screen.getByRole("button", { name: "Search" }));
  await user.click(await screen.findByRole("button", { name: "Show full text" }));

  await waitFor(() =>
    expect(fakeClient.getPageText).toHaveBeenCalledWith("core-rules", 134),
  );
  expect(await screen.findByText("Full critical hit page text.")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Hide full text" }));
  await user.click(screen.getByRole("button", { name: "Show full text" }));

  expect(fakeClient.getPageText).toHaveBeenCalledTimes(1);
});

it("shows search errors and ignores blank submissions", async () => {
  const user = userEvent.setup();
  const fakeClient = client({
    searchExact: vi.fn().mockRejectedValue("bad search"),
  });

  renderApp(<SearchTab client={fakeClient} onOpenPdfPage={vi.fn()} />);

  fireEvent.submit(screen.getByRole("searchbox", { name: "Search book text" }).closest("form")!);
  expect(fakeClient.searchExact).not.toHaveBeenCalled();

  await user.type(screen.getByRole("searchbox", { name: "Search book text" }), "critical hit");
  await user.click(screen.getByRole("button", { name: "Search" }));

  expect(await screen.findByText("Unknown error")).toBeInTheDocument();
});

it("ignores aborted searches", async () => {
  const user = userEvent.setup();
  const fakeClient = client({
    searchExact: vi.fn().mockRejectedValue(new DOMException("Aborted", "AbortError")),
  });

  renderApp(<SearchTab client={fakeClient} onOpenPdfPage={vi.fn()} />);

  await user.type(screen.getByRole("searchbox", { name: "Search book text" }), "critical hit");
  await user.click(screen.getByRole("button", { name: "Search" }));

  expect(await screen.findByRole("searchbox", { name: "Search book text" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps the newest search loading when an older search resolves last", async () => {
  const user = userEvent.setup();
  let resolveFirst: Parameters<ConstructorParameters<typeof Promise>[0]>[0];
  let resolveSecond: Parameters<ConstructorParameters<typeof Promise>[0]>[0];
  const firstResponse = {
    query: "critical",
    scope: {
      label: "active_source_set",
      source_set_id: "rules-core",
      book_ids: ["core-rules"],
      all_books: false,
    },
    hits: [],
  };
  const secondResponse = {
    ...firstResponse,
    query: "critical hit",
    hits: [
      {
        rank: 1,
        book_id: "core-rules",
        title: "Core Rules",
        category: "Rules",
        page_id: "core-rules:134",
        page_number: 134,
        snippet: "...critical hit...",
        score: -1,
      },
    ],
  };
  const fakeClient = client({
    searchExact: vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecond = resolve;
          }),
      ),
  });

  renderApp(<SearchTab client={fakeClient} onOpenPdfPage={vi.fn()} />);

  const searchbox = screen.getByRole("searchbox", { name: "Search book text" });
  const form = searchbox.closest("form")!;
  await user.type(searchbox, "critical");
  fireEvent.submit(form);
  await user.type(searchbox, " hit");
  fireEvent.submit(form);

  resolveFirst!(firstResponse);
  await waitFor(() => expect(screen.getByText("Searching...")).toBeInTheDocument());

  resolveSecond!(secondResponse);
  expect(await screen.findByText("...critical hit...")).toBeInTheDocument();
});

it("reports full page text fetch errors", async () => {
  const user = userEvent.setup();
  const fakeClient = client({
    getPageText: vi.fn().mockRejectedValue(new Error("Page text unavailable")),
  });

  renderApp(<SearchTab client={fakeClient} onOpenPdfPage={vi.fn()} />);

  await user.type(screen.getByRole("searchbox", { name: "Search book text" }), "critical hit");
  await user.click(screen.getByRole("button", { name: "Search" }));
  await user.click(await screen.findByRole("button", { name: "Show full text" }));

  expect(await screen.findByText("Page text unavailable")).toBeInTheDocument();
});

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./apiError";
import { apiClient, requestJson } from "./apiClient";

function mockFetch(response: Response) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("requestJson", () => {
  it("returns parsed JSON for successful responses", async () => {
    mockFetch(Response.json({ status: "ok" }));

    await expect(requestJson("/api/health")).resolves.toEqual({ status: "ok" });
  });

  it("maps API error detail into ApiError", async () => {
    mockFetch(Response.json({ detail: "Book not found" }, { status: 404 }));

    await expect(requestJson("/api/books/missing")).rejects.toMatchObject({
      status: 404,
      message: "Book not found",
    });
  });

  it("falls back to status text when an error body has no detail", async () => {
    mockFetch(Response.json({ message: "No detail" }, { status: 409 }));

    await expect(requestJson("/api/books/core-rules/pdf")).rejects.toMatchObject({
      status: 409,
      message: "",
    });
  });

  it("maps network failures to local API unavailable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));

    await expect(requestJson("/api/health")).rejects.toEqual(
      new ApiError(0, "Local API unavailable"),
    );
  });

  it("preserves abort errors for request cancellation", async () => {
    const abortError = new DOMException("Aborted", "AbortError");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(abortError);

    await expect(requestJson("/api/search/exact")).rejects.toBe(abortError);
  });

  it("falls back to status text when error JSON cannot be parsed", async () => {
    mockFetch(new Response("not json", { status: 500, statusText: "Broken" }));

    await expect(requestJson("/api/books")).rejects.toMatchObject({
      status: 500,
      message: "Broken",
    });
  });
});

describe("apiClient", () => {
  it("requests the current read endpoints", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => Promise.resolve(Response.json({ ok: true })));
    const signal = new AbortController().signal;

    await apiClient.getHealth({ signal });
    await apiClient.listBooks({ signal });
    await apiClient.listSourceSets({ signal });
    await apiClient.listSourceSetBooks("rules/core", { signal });
    await apiClient.getPageText("core rules", 134, { signal });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/health",
      expect.objectContaining({ signal }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/books",
      expect.objectContaining({ signal }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/source-sets",
      expect.objectContaining({ signal }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/source-sets/rules%2Fcore/books",
      expect.objectContaining({ signal }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/books/core%20rules/pages/134/text",
      expect.objectContaining({ signal }),
    );
  });

  it("requests source-set book toggles through the canonical endpoint", async () => {
    const fetchMock = mockFetch(
      Response.json({
        source_set_id: "rules-core",
        book_id: "core-rules",
        title: "Core Rules",
        category: "Core",
        enabled: false,
        search_ready: true,
      }),
    );

    await apiClient.setSourceSetBook("rules-core", "core-rules", false);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/source-sets/rules-core/books/core-rules",
      expect.objectContaining({
        body: JSON.stringify({ enabled: false }),
        method: "PUT",
      }),
    );
  });

  it("encodes exact-search query parameters", async () => {
    const fetchMock = mockFetch(
      Response.json({
        query: "critical hit",
        scope: {
          label: "active_source_set",
          source_set_id: "rules-core",
          book_ids: ["core-rules"],
          all_books: false,
        },
        hits: [],
      }),
    );

    await apiClient.searchExact("critical hit", { limit: 7 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search/exact?query=critical+hit&limit=7",
      expect.any(Object),
    );
  });

  it("uses the default exact-search limit", async () => {
    const fetchMock = mockFetch(
      Response.json({
        query: "mutation",
        scope: {
          label: "active_source_set",
          source_set_id: "rules-core",
          book_ids: [],
          all_books: false,
        },
        hits: [],
      }),
    );

    await apiClient.searchExact("mutation");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search/exact?query=mutation&limit=20",
      expect.any(Object),
    );
  });
});

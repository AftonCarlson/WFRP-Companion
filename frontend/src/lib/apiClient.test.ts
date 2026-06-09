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
    await apiClient.getRetrievalStatus({ signal });
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
      "/api/retrieval/status",
      expect.objectContaining({ signal }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/source-sets",
      expect.objectContaining({ signal }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/source-sets/rules%2Fcore/books",
      expect.objectContaining({ signal }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
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

  it("streams chat message events from newline-delimited JSON", async () => {
    const chunks = [
      '{"type":"accepted","user_message":{"id":"m1","thread_id":"t1","role":"user","content":"Hi","created_at":"now"},"model_run":{"id":"r1","thread_id":"t1","user_message_id":"m1","assistant_message_id":null,"retrieval_run_id":null,"retry_of_model_run_id":null,"status":"calling_model","provider":"openai","model":"gpt-5.4-mini","error_code":null,"error_message":null,"retryable":false},"citations":[]}\n',
      '{"type":"delta","text_delta":"Hello"}\n',
      '{"type":"completed","assistant_message":{"id":"m2","thread_id":"t1","role":"assistant","content":"Hello","created_at":"later"},"model_run":{"id":"r1","thread_id":"t1","user_message_id":"m1","assistant_message_id":"m2","retrieval_run_id":null,"retry_of_model_run_id":null,"status":"completed","provider":"openai","model":"gpt-5.4-mini","error_code":null,"error_message":null,"retryable":false},"citations":[]}\n',
    ];
    const body = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(new TextEncoder().encode(chunk));
        }
        controller.close();
      },
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(body, { status: 200 }));
    const events: string[] = [];

    await apiClient.streamChatMessage("thread 1", {
      content: "Hi",
      idempotency_key: "send-1",
      onEvent: (event) => events.push(event.type),
    });

    expect(events).toEqual(["accepted", "delta", "completed"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/chat/threads/thread%201/messages/stream",
      expect.objectContaining({
        body: JSON.stringify({ content: "Hi", idempotency_key: "send-1" }),
        method: "POST",
      }),
    );
  });

  it("streams a final buffered chat event without a trailing newline", async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('{"type":"delta","text_delta":"Hello"}'),
        );
        controller.close();
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(body, { status: 200 }));
    const events: string[] = [];

    await apiClient.streamChatMessage("thread-1", {
      content: "Hi",
      onEvent: (event) => events.push(event.type),
    });

    expect(events).toEqual(["delta"]);
  });

  it("maps failed stream responses into ApiError", async () => {
    mockFetch(Response.json({ detail: "Thread not found" }, { status: 404 }));

    await expect(
      apiClient.streamChatMessage("missing", {
        content: "Hi",
        onEvent: () => {},
      }),
    ).rejects.toMatchObject({
      status: 404,
      message: "Thread not found",
    });
  });

  it("rejects stream responses without a body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      body: null,
      status: 200,
      statusText: "OK",
    } as Response);

    await expect(
      apiClient.streamChatMessage("thread-1", {
        content: "Hi",
        onEvent: () => {},
      }),
    ).rejects.toEqual(
      new ApiError(0, "Local API response did not include a stream"),
    );
  });

  it("maps stream network failures and preserves stream abort errors", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("offline"))
      .mockRejectedValueOnce(new DOMException("Aborted", "AbortError"));

    await expect(
      apiClient.streamChatMessage("thread-1", {
        content: "Hi",
        onEvent: () => {},
      }),
    ).rejects.toEqual(new ApiError(0, "Local API unavailable"));
    const abortPromise = apiClient.streamChatMessage("thread-1", {
      content: "Hi",
      onEvent: () => {},
    });
    await expect(abortPromise).rejects.toMatchObject({ name: "AbortError" });
  });
});

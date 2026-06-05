import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "../lib/apiClient";
import { ApiError } from "../lib/apiError";
import { useInitialWorkspaceData } from "./useInitialWorkspaceData";

function client(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    getHealth: vi.fn().mockResolvedValue({ status: "ok", database: "ready" }),
    listBooks: vi.fn().mockResolvedValue({
      books: [
        {
          id: "core-rules",
          title: "Core Rules",
          category: "Core Book & GM Essentials",
          relative_path: "Core/Core Rules.pdf",
          page_count: 1,
          copy_status: "copied",
          text_status: "imported",
          search_status: "indexed",
          visual_status: "not_scanned",
          reader_ready: true,
          search_ready: true,
          fully_ready: false,
          needs_attention: false,
        },
      ],
    }),
    listSourceSets: vi.fn().mockResolvedValue({
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
    }),
    listSourceSetBooks: vi.fn().mockResolvedValue({
      source_set_id: "rules-core",
      books: [
        {
          source_set_id: "rules-core",
          book_id: "core-rules",
          title: "Core Rules",
          category: "Core Book & GM Essentials",
          enabled: true,
          search_ready: true,
        },
      ],
    }),
    setSourceSetBook: vi.fn(),
    searchExact: vi.fn(),
    getPageText: vi.fn(),
    ...overrides,
  } as ApiClient;
}

describe("useInitialWorkspaceData", () => {
  it("loads books, source sets, and active source-set books", async () => {
    const fakeClient = client();

    const { result } = renderHook(() => useInitialWorkspaceData(fakeClient));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.data?.activeSourceSetId).toBe("rules-core");
    expect(result.current.data?.books[0].title).toBe("Core Rules");
    expect(result.current.data?.sourceSetBooks[0].enabled).toBe(true);
    expect(fakeClient.listSourceSetBooks).toHaveBeenCalledWith(
      "rules-core",
      expect.any(Object),
    );
  });

  it("handles a missing active source set without a book-scope request", async () => {
    const fakeClient = client({
      listSourceSets: vi.fn().mockResolvedValue({
        active_source_set_id: null,
        source_sets: [],
      }),
    });

    const { result } = renderHook(() => useInitialWorkspaceData(fakeClient));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data?.activeSourceSetId).toBeNull();
    expect(result.current.data?.sourceSetBooks).toEqual([]);
    expect(fakeClient.listSourceSetBooks).not.toHaveBeenCalled();
  });

  it("reports local API failures", async () => {
    const fakeClient = client({
      getHealth: vi.fn().mockRejectedValue(new ApiError(0, "Local API unavailable")),
    });

    const { result } = renderHook(() => useInitialWorkspaceData(fakeClient));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Local API unavailable");
    expect(result.current.data).toBeNull();
  });

  it("ignores aborted initial loading requests", async () => {
    const fakeClient = client({
      getHealth: vi.fn().mockRejectedValue(new DOMException("Aborted", "AbortError")),
    });

    const { result } = renderHook(() => useInitialWorkspaceData(fakeClient));
    await waitFor(() => expect(fakeClient.getHealth).toHaveBeenCalled());

    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
  });
});

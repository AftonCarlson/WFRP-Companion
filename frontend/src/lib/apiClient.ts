import { ApiError } from "./apiError";
import type {
  BooksResponse,
  ExactSearchResponse,
  HealthResponse,
  PageTextResponse,
  SourceSetBookResponse,
  SourceSetBooksResponse,
  SourceSetsResponse,
} from "../types/api";

export type RequestOptions = {
  signal?: AbortSignal;
};

type ErrorBody = {
  detail?: string;
};

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ErrorBody;
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: {
        Accept: "application/json",
        ...init.headers,
      },
      ...init,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "Local API unavailable");
  }

  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }

  return (await response.json()) as T;
}

export const apiClient = {
  getHealth(options?: RequestOptions): Promise<HealthResponse> {
    return requestJson<HealthResponse>("/api/health", {
      signal: options?.signal,
    });
  },

  listBooks(options?: RequestOptions): Promise<BooksResponse> {
    return requestJson<BooksResponse>("/api/books", {
      signal: options?.signal,
    });
  },

  listSourceSets(options?: RequestOptions): Promise<SourceSetsResponse> {
    return requestJson<SourceSetsResponse>("/api/source-sets", {
      signal: options?.signal,
    });
  },

  listSourceSetBooks(
    sourceSetId: string,
    options?: RequestOptions,
  ): Promise<SourceSetBooksResponse> {
    return requestJson<SourceSetBooksResponse>(
      `/api/source-sets/${encodeURIComponent(sourceSetId)}/books`,
      { signal: options?.signal },
    );
  },

  setSourceSetBook(
    sourceSetId: string,
    bookId: string,
    enabled: boolean,
  ): Promise<SourceSetBookResponse> {
    return requestJson<SourceSetBookResponse>(
      `/api/source-sets/${encodeURIComponent(sourceSetId)}/books/${encodeURIComponent(bookId)}`,
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ enabled }),
      },
    );
  },

  searchExact(
    query: string,
    options?: RequestOptions & { limit?: number },
  ): Promise<ExactSearchResponse> {
    const params = new URLSearchParams({
      query,
      limit: String(options?.limit ?? 20),
    });
    return requestJson<ExactSearchResponse>(`/api/search/exact?${params}`, {
      signal: options?.signal,
    });
  },

  getPageText(
    bookId: string,
    pageNumber: number,
    options?: RequestOptions,
  ): Promise<PageTextResponse> {
    return requestJson<PageTextResponse>(
      `/api/books/${encodeURIComponent(bookId)}/pages/${pageNumber}/text`,
      { signal: options?.signal },
    );
  },
};

export type ApiClient = typeof apiClient;

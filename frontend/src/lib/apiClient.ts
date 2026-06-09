import { ApiError } from "./apiError";
import type {
  BooksResponse,
  ChatStreamEvent,
  ChatThreadDetailResponse,
  ChatThreadResponse,
  ChatThreadsResponse,
  ExactSearchResponse,
  HealthResponse,
  PageTextResponse,
  RetrievalStatusResponse,
  SendChatMessageResponse,
  SourceSetBookResponse,
  SourceSetBooksResponse,
  SourceSetsResponse,
} from "../types/api";

export type RequestOptions = {
  signal?: AbortSignal;
};

export type StreamChatMessageOptions = {
  content: string;
  idempotency_key?: string;
  onEvent: (event: ChatStreamEvent) => void;
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

  getRetrievalStatus(options?: RequestOptions): Promise<RetrievalStatusResponse> {
    return requestJson<RetrievalStatusResponse>("/api/retrieval/status", {
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

  createChatThread(options?: {
    title?: string | null;
    source_set_id?: string | null;
  }): Promise<ChatThreadResponse> {
    return requestJson<ChatThreadResponse>("/api/chat/threads", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(options ?? {}),
    });
  },

  listChatThreads(options?: RequestOptions): Promise<ChatThreadsResponse> {
    return requestJson<ChatThreadsResponse>("/api/chat/threads", {
      signal: options?.signal,
    });
  },

  getChatThread(
    threadId: string,
    options?: RequestOptions,
  ): Promise<ChatThreadDetailResponse> {
    return requestJson<ChatThreadDetailResponse>(
      `/api/chat/threads/${encodeURIComponent(threadId)}`,
      { signal: options?.signal },
    );
  },

  sendChatMessage(
    threadId: string,
    content: string,
    idempotencyKey: string,
  ): Promise<SendChatMessageResponse> {
    return requestJson<SendChatMessageResponse>(
      `/api/chat/threads/${encodeURIComponent(threadId)}/messages`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content, idempotency_key: idempotencyKey }),
      },
    );
  },

  retryModelRun(
    modelRunId: string,
    idempotencyKey: string,
  ): Promise<SendChatMessageResponse> {
    return requestJson<SendChatMessageResponse>(
      `/api/chat/model-runs/${encodeURIComponent(modelRunId)}/retry`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ idempotency_key: idempotencyKey }),
      },
    );
  },

  async streamChatMessage(
    threadId: string,
    options: StreamChatMessageOptions,
  ): Promise<void> {
    let response: Response;
    try {
      response = await fetch(
        `/api/chat/threads/${encodeURIComponent(threadId)}/messages/stream`,
        {
          method: "POST",
          headers: {
            Accept: "application/x-ndjson",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            content: options.content,
            idempotency_key: options.idempotency_key,
          }),
          signal: options.signal,
        },
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw error;
      }
      throw new ApiError(0, "Local API unavailable");
    }

    if (!response.ok) {
      throw new ApiError(response.status, await parseError(response));
    }
    if (!response.body) {
      throw new ApiError(0, "Local API response did not include a stream");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed) {
          options.onEvent(JSON.parse(trimmed) as ChatStreamEvent);
        }
      }
      if (done) {
        break;
      }
    }
    const finalLine = buffer.trim();
    if (finalLine) {
      options.onEvent(JSON.parse(finalLine) as ChatStreamEvent);
    }
  },
};

export type ApiClient = typeof apiClient;

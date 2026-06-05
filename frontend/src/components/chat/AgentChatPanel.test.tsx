import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderApp } from "../../test/render";
import type { ApiClient } from "../../lib/apiClient";
import { AgentChatHeaderControls, AgentChatPanel } from "./AgentChatPanel";

function AgentChatHarness() {
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <>
      <AgentChatHeaderControls
        historyOpen={historyOpen}
        setHistoryOpen={setHistoryOpen}
      />
      <AgentChatPanel historyOpen={historyOpen} />
    </>
  );
}

describe("AgentChatPanel", () => {
  it("renders a scrollable transcript and controlled composer", async () => {
    const user = userEvent.setup();
    renderApp(<AgentChatHarness />);

    const transcript = screen.getByRole("log", { name: "Agent transcript" });
    const composer = screen.getByRole("textbox", { name: "Message" });

    expect(transcript).toBeInTheDocument();
    expect(screen.queryByText("Game Master Aid")).not.toBeInTheDocument();
    expect(screen.getByText(/Familiar ready/i)).toBeInTheDocument();
    await user.type(composer, "Look up the grappling rule.");

    expect(composer).toHaveValue("Look up the grappling rule.");
    expect(
      composer.closest(".agent-chat__composer-field"),
    ).toContainElement(screen.getByRole("button", { name: "Send message" }));
    expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled();
  });

  it("opens the placeholder chat history menu", async () => {
    const user = userEvent.setup();
    renderApp(<AgentChatHarness />);

    await user.click(screen.getByRole("button", { name: "Open chat history" }));

    expect(screen.getByText("Chat history")).toBeInTheDocument();
    expect(
      screen.getByText(/chat persistence arrives in the agent phase/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Close chat history" }),
    ).toBeInTheDocument();
  });

  it("streams assistant output into the transcript", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
          model_run: modelRun("calling_model"),
          citations: [],
        });
        options.onEvent({ type: "delta", text_delta: "Critical " });
        options.onEvent({ type: "delta", text_delta: "hits" });
        options.onEvent({
          type: "completed",
          assistant_message: {
            id: "m2",
            thread_id: threadId,
            role: "assistant",
            content: "Critical hits",
            created_at: "later",
          },
          model_run: modelRun("completed"),
          citations: [
            {
              book_id: "core-rules",
              title: "Core Rules",
              category: "Core",
              page_id: "core-rules:1",
              page_number: 1,
              pdf_page_number: 1,
              page_label: null,
              snippet: "Critical hit",
              rank: 1,
              score: -1,
            },
          ],
        });
      },
    });
    const opened: string[] = [];
    renderApp(
      <AgentChatPanel
        client={client}
        historyOpen={false}
        onOpenCitation={(citation) => opened.push(citation.book_id)}
      />,
    );

    await user.type(screen.getByRole("textbox", { name: "Message" }), "critical hit");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Critical hits")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Core Rules page 1" }));
    expect(opened).toEqual(["core-rules"]);
  });

  it("renders streamed markdown tables as readable tables", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
        });
        options.onEvent({
          type: "completed",
          assistant_message: {
            id: "m2",
            thread_id: threadId,
            role: "assistant",
            content:
              "### Critical Hits\n\n| Rule | What happens |\n|---|---|\n| Trigger | Roll **10** on damage. |",
            created_at: "later",
          },
          citations: [],
        });
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "critical hit");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByRole("heading", { name: "Critical Hits" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Rule" })).toBeInTheDocument();
    expect(screen.getByText("10").closest("strong")).not.toBeNull();
  });

  it("labels citation buttons with printed page ranges and keeps PDF target hidden", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
        });
        options.onEvent({
          type: "retrieval",
          citations: [
            {
              book_id: "core-rules",
              title: "Core Rules",
              category: "Core",
              page_id: "core-rules:133",
              page_number: 133,
              pdf_page_number: 133,
              page_label: "132",
              page_range_label: "132-133",
              snippet: "Critical hit",
              rank: 1,
              score: -1,
            },
          ],
        });
      },
    });
    const opened: number[] = [];
    renderApp(
      <AgentChatPanel
        client={client}
        historyOpen={false}
        onOpenCitation={(citation) => opened.push(citation.pdf_page_number)}
      />,
    );

    await user.type(screen.getByRole("textbox", { name: "Message" }), "critical hit");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    await user.click(
      await screen.findByRole("button", {
        name: "Open Core Rules printed pages 132-133",
      }),
    );
    expect(opened).toEqual([133]);
  });

  it("keeps a single thread while sending multiple messages", async () => {
    const user = userEvent.setup();
    const createChatThread = vi.fn(chatClient({}).createChatThread);
    const streamChatMessage = vi.fn(async (threadId, options) => {
      options.onEvent({
        type: "accepted",
        user_message: {
          id: `m-${options.content}`,
          thread_id: threadId,
          role: "user",
          content: options.content,
          created_at: "now",
        },
      });
      options.onEvent({
        type: "completed",
        assistant_message: {
          id: `a-${options.content}`,
          thread_id: threadId,
          role: "assistant",
          content: `Answered ${options.content}`,
          created_at: "later",
        },
        citations: [],
      });
    });
    const client = chatClient({ createChatThread, streamChatMessage });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);
    const composer = screen.getByRole("textbox", { name: "Message" });

    await user.type(composer, "first");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByText("Answered first");
    await user.type(composer, "second");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("Answered second")).toBeInTheDocument();
    expect(createChatThread).toHaveBeenCalledTimes(1);
    expect(streamChatMessage).toHaveBeenCalledTimes(2);
  });

  it("handles retrieval, completion fallback content, and shift-enter composer input", async () => {
    const user = userEvent.setup();
    const opened: string[] = [];
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
        });
        options.onEvent({
          type: "retrieval",
          citations: [
            {
              book_id: "core-rules",
              title: "Core Rules",
              category: "Core",
              page_id: "core-rules:134",
              page_number: 134,
              pdf_page_number: 134,
              page_label: null,
              snippet: "Critical hit",
              rank: 1,
              score: -1,
            },
          ],
        });
        options.onEvent({ type: "delta", text_delta: "Fallback " });
        options.onEvent({ type: "completed", model_run: null });
      },
    });
    renderApp(
      <AgentChatPanel
        client={client}
        historyOpen={false}
        onOpenCitation={(citation) => opened.push(citation.page_id)}
      />,
    );
    const composer = screen.getByRole("textbox", { name: "Message" });

    await user.type(composer, "critical");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    expect(composer).toHaveValue("critical\n");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Fallback")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Core Rules page 134" }));
    expect(opened).toEqual(["core-rules:134"]);
  });

  it("ignores empty sends and displays non-abort stream errors", async () => {
    const user = userEvent.setup();
    const streamChatMessage = vi.fn(async () => {
      throw new Error("server gone");
    });
    const client = chatClient({ streamChatMessage });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(streamChatMessage).not.toHaveBeenCalled();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "doom");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("server gone")).toBeInTheDocument();
  });

  it("ignores aborted stream sends without surfacing panel errors", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage() {
        throw new DOMException("Aborted", "AbortError");
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "doom");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled(),
    );
    expect(screen.queryByText("Aborted")).not.toBeInTheDocument();
  });

  it("shows failed streamed provider-unavailable runs", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
          model_run: modelRun("failed", "provider_unavailable"),
          citations: [],
        });
        options.onEvent({
          type: "failed",
          model_run: modelRun("failed", "provider_unavailable"),
          citations: [],
          error_message: "OPENAI_API_KEY is not configured.",
        });
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "fear");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(
      await screen.findByText("OPENAI_API_KEY is not configured."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry message" })).toBeInTheDocument();
  });

  it("uses model-run and default messages for failed stream events", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
          model_run: {
            ...modelRun("failed", "quota_exceeded"),
            error_message: "Quota exhausted.",
          },
        });
        options.onEvent({
          type: "failed",
          model_run: {
            ...modelRun("failed", "quota_exceeded"),
            error_message: "Quota exhausted.",
          },
        });
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "fear");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Quota exhausted.")).toBeInTheDocument();
  });

  it("falls back to a generic failed stream message when no error is provided", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
          model_run: modelRun("calling_model"),
        });
        options.onEvent({ type: "failed" });
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "fear");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(
      await screen.findByText("Familiar could not complete the response."),
    ).toBeInTheDocument();
  });

  it("retries failed messages through the retry endpoint", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
          model_run: modelRun("failed", "provider_unavailable"),
          citations: [],
        });
        options.onEvent({
          type: "failed",
          model_run: modelRun("failed", "provider_unavailable"),
          citations: [],
          error_message: "OPENAI_API_KEY is not configured.",
        });
      },
      async retryModelRun(modelRunId) {
        return {
          thread: {
            id: "thread-1",
            title: null,
            active_source_set_id: "rules-core",
            source_book_count: 1,
            created_at: "now",
            updated_at: "later",
          },
          user_message: {
            id: "m1",
            thread_id: "thread-1",
            role: "user",
            content: "fear",
            created_at: "now",
          },
          assistant_message: null,
          model_run: {
            ...modelRun("failed", "provider_unavailable"),
            id: `${modelRunId}-retry`,
            retry_of_model_run_id: modelRunId,
            error_message: "Still missing OPENAI_API_KEY.",
          },
          citations: [],
        };
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "fear");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    await user.click(await screen.findByRole("button", { name: "Retry message" }));

    expect(await screen.findByText("Still missing OPENAI_API_KEY.")).toBeInTheDocument();
  });

  it("renders successful retry content and retry citations", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
          model_run: modelRun("failed", "provider_unavailable"),
        });
        options.onEvent({ type: "failed", model_run: modelRun("failed") });
      },
      async retryModelRun() {
        return {
          thread: {
            id: "thread-1",
            title: null,
            active_source_set_id: "rules-core",
            source_book_count: 1,
            created_at: "now",
            updated_at: "later",
          },
          user_message: {
            id: "m1",
            thread_id: "thread-1",
            role: "user",
            content: "fear",
            created_at: "now",
          },
          assistant_message: {
            id: "m2",
            thread_id: "thread-1",
            role: "assistant",
            content: "Retry succeeded.",
            created_at: "later",
          },
          model_run: modelRun("completed"),
          citations: [
            {
              book_id: "core-rules",
              title: "Core Rules",
              category: "Core",
              page_id: "core-rules:2",
              page_number: 2,
              pdf_page_number: 2,
              page_label: null,
              snippet: "Fear",
              rank: 1,
              score: -2,
            },
          ],
        };
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "fear");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    await user.click(await screen.findByRole("button", { name: "Retry message" }));

    expect(await screen.findByText("Retry succeeded.")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open Core Rules page 2" }),
    ).toBeInTheDocument();
  });

  it("surfaces retry errors and ignores retry aborts", async () => {
    const user = userEvent.setup();
    const retryModelRun = vi
      .fn()
      .mockRejectedValueOnce(new DOMException("Aborted", "AbortError"))
      .mockRejectedValueOnce(new Error("retry broke"));
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
          model_run: modelRun("failed"),
        });
        options.onEvent({ type: "failed", model_run: modelRun("failed") });
      },
      retryModelRun,
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "fear");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    const retry = await screen.findByRole("button", { name: "Retry message" });
    await user.click(retry);
    expect(screen.queryByText("Aborted")).not.toBeInTheDocument();
    await user.click(retry);

    expect(await screen.findByText("retry broke")).toBeInTheDocument();
  });
});

function modelRun(status: string, errorCode: string | null = null) {
  return {
    id: "r1",
    thread_id: "thread-1",
    user_message_id: "m1",
    assistant_message_id: status === "completed" ? "m2" : null,
    retrieval_run_id: null,
    retry_of_model_run_id: null,
    status,
    provider: "openai",
    model: "gpt-5.4-mini",
    provider_response_id: status === "completed" ? "resp-1" : null,
    error_code: errorCode,
    error_message: errorCode,
    input_tokens: status === "completed" ? 10 : null,
    output_tokens: status === "completed" ? 2 : null,
    retryable: status === "failed",
  };
}

function chatClient(
  overrides: Partial<ApiClient>,
): ApiClient {
  return {
    getHealth: async () => ({ status: "ok", database: "ready" }),
    getPageText: async () => ({
      page_id: "p1",
      book_id: "core-rules",
      page_number: 1,
      page_label: null,
      text: "",
      text_chars: 0,
    }),
    listBooks: async () => ({ books: [] }),
    listSourceSets: async () => ({ active_source_set_id: null, source_sets: [] }),
    listSourceSetBooks: async () => ({ source_set_id: "rules-core", books: [] }),
    searchExact: async () => ({
      query: "",
      scope: { label: "all", source_set_id: null, book_ids: null, all_books: true },
      hits: [],
    }),
    setSourceSetBook: async () => ({
      source_set_id: "rules-core",
      book_id: "core-rules",
      title: "Core Rules",
      category: "Core",
      enabled: true,
      search_ready: true,
    }),
    createChatThread: async () => ({
      id: "thread-1",
      title: null,
      active_source_set_id: "rules-core",
      source_book_count: 1,
      created_at: "now",
      updated_at: "now",
    }),
    getChatThread: async () => ({
      thread: {
        id: "thread-1",
        title: null,
        active_source_set_id: "rules-core",
        source_book_count: 1,
        created_at: "now",
        updated_at: "now",
      },
      source_book_ids: ["core-rules"],
      turns: [],
    }),
    listChatThreads: async () => ({ threads: [] }),
    retryModelRun: async () => {
      throw new Error("not implemented in test");
    },
    sendChatMessage: async () => {
      throw new Error("not implemented in test");
    },
    streamChatMessage: async () => {},
    ...overrides,
  };
}

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

  it("loads chat history threads when the drawer is open", async () => {
    const client = chatClient({
      listChatThreads: async () => ({
        threads: [
          {
            id: "thread-old",
            title: "Old Rules Chat",
            active_source_set_id: "rules-core",
            source_book_count: 1,
            created_at: "2026-06-06T00:00:00Z",
            updated_at: "not-a-date",
          },
        ],
      }),
    });
    renderApp(<AgentChatPanel client={client} historyOpen={true} />);

    expect(screen.getByText("Chat history")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Old Rules Chat/ })).toBeInTheDocument();
    expect(screen.getByText("not-a-date")).toBeInTheDocument();
    expect(
      screen.queryByText(/chat persistence arrives in the agent phase/i),
    ).not.toBeInTheDocument();
  });

  it("selects a stored thread and continues sending in that thread", async () => {
    const user = userEvent.setup();
    const streamChatMessage = vi.fn(async (threadId, options) => {
      options.onEvent({
        type: "accepted",
        user_message: {
          id: "m-next",
          thread_id: threadId,
          role: "user",
          content: options.content,
          created_at: "now",
        },
        model_run: { ...modelRun("calling_model"), id: "run-next", thread_id: threadId },
      });
      options.onEvent({
        type: "completed",
        assistant_message: {
          id: "a-next",
          thread_id: threadId,
          role: "assistant",
          content: "Continued answer.",
          created_at: "later",
        },
        model_run: { ...modelRun("completed"), id: "run-next", thread_id: threadId },
        citations: [],
      });
    });
    const client = chatClient({
      listChatThreads: async () => ({
        threads: [
          {
            id: "thread-old",
            title: "Old Rules Chat",
            active_source_set_id: "rules-core",
            source_book_count: 1,
            created_at: "2026-06-06T00:00:00Z",
            updated_at: "2026-06-06T00:02:00Z",
          },
        ],
      }),
      getChatThread: async () => ({
        thread: {
          id: "thread-old",
          title: "Old Rules Chat",
          active_source_set_id: "rules-core",
          source_book_count: 1,
          created_at: "2026-06-06T00:00:00Z",
          updated_at: "2026-06-06T00:02:00Z",
        },
        source_book_ids: ["core-rules"],
        turns: [
          {
            user_message: {
              id: "m-old",
              thread_id: "thread-old",
              role: "user",
              content: "Loaded question",
              created_at: "then",
            },
            assistant_message: {
              id: "a-old",
              thread_id: "thread-old",
              role: "assistant",
              content: "Loaded answer",
              created_at: "then",
            },
            model_run: { ...modelRun("completed"), id: "run-old", thread_id: "thread-old" },
            citations: [],
            research_events: [
              {
                type: "research_plan",
                label: "Research plan accepted",
                metadata: {},
              },
              {
                type: "evidence_validation",
                label: "Evidence sufficient; 1 accepted, 0 partial",
                metadata: {},
              },
            ],
          },
        ],
      }),
      streamChatMessage,
    });
    renderApp(<AgentChatPanel client={client} historyOpen={true} />);

    await user.click(await screen.findByRole("button", { name: /Old Rules Chat/ }));
    expect(await screen.findByText("Loaded question")).toBeInTheDocument();
    expect(screen.getByText("Loaded answer")).toBeInTheDocument();
    expect(
      screen.getAllByText("Evidence sufficient; 1 accepted, 0 partial").length,
    ).toBeGreaterThan(0);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "continue");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Continued answer.")).toBeInTheDocument();
    expect(streamChatMessage).toHaveBeenCalledWith(
      "thread-old",
      expect.objectContaining({ content: "continue" }),
    );
  });

  it("disables history thread selection while a message is streaming", async () => {
    const user = userEvent.setup();
    let finishStream!: () => void;
    const streamChatMessage = vi.fn(
      async (threadId, options) =>
        new Promise<void>((resolve) => {
          options.onEvent({
            type: "accepted",
            user_message: {
              id: "m-active",
              thread_id: threadId,
              role: "user",
              content: options.content,
              created_at: "now",
            },
            model_run: { ...modelRun("calling_model"), id: "run-active", thread_id: threadId },
          });
          finishStream = () => {
            options.onEvent({
              type: "completed",
              assistant_message: {
                id: "a-active",
                thread_id: threadId,
                role: "assistant",
                content: "Done.",
                created_at: "later",
              },
              model_run: { ...modelRun("completed"), id: "run-active", thread_id: threadId },
              citations: [],
            });
            resolve();
          };
        }),
    );
    const client = chatClient({
      listChatThreads: async () => ({
        threads: [
          {
            id: "thread-old",
            title: "Old Rules Chat",
            active_source_set_id: "rules-core",
            source_book_count: 1,
            created_at: "2026-06-06T00:00:00Z",
            updated_at: "2026-06-06T00:02:00Z",
          },
        ],
      }),
      streamChatMessage,
    });
    renderApp(<AgentChatPanel client={client} historyOpen={true} />);

    const historyButton = await screen.findByRole("button", { name: /Old Rules Chat/ });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "streaming");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(historyButton).toBeDisabled());
    finishStream();
    expect(await screen.findByText("Done.")).toBeInTheDocument();
  });

  it("ignores late history loads while a message is streaming", async () => {
    const user = userEvent.setup();
    let resolveHistory!: (
      detail: Awaited<ReturnType<ApiClient["getChatThread"]>>,
    ) => void;
    let finishStream!: () => void;
    const streamChatMessage = vi.fn(
      async (threadId, options) =>
        new Promise<void>((resolve) => {
          options.onEvent({
            type: "accepted",
            thread: {
              id: threadId,
              title: null,
              active_source_set_id: "rules-core",
              source_book_count: 1,
              created_at: "now",
              updated_at: "now",
            },
            user_message: {
              id: "m-active",
              thread_id: threadId,
              role: "user",
              content: options.content,
              created_at: "now",
            },
            model_run: { ...modelRun("calling_model"), id: "run-active", thread_id: threadId },
          });
          finishStream = () => {
            options.onEvent({
              type: "completed",
              thread: {
                id: threadId,
                title: null,
                active_source_set_id: "rules-core",
                source_book_count: 1,
                created_at: "now",
                updated_at: "later",
              },
              assistant_message: {
                id: "a-active",
                thread_id: threadId,
                role: "assistant",
                content: "Live answer.",
                created_at: "later",
              },
              model_run: { ...modelRun("completed"), id: "run-active", thread_id: threadId },
              citations: [],
            });
            resolve();
          };
        }),
    );
    const client = chatClient({
      listChatThreads: async () => ({
        threads: [
          {
            id: "thread-old",
            title: "Old Rules Chat",
            active_source_set_id: "rules-core",
            source_book_count: 1,
            created_at: "2026-06-06T00:00:00Z",
            updated_at: "2026-06-06T00:02:00Z",
          },
        ],
      }),
      getChatThread: async () =>
        new Promise((resolve) => {
          resolveHistory = resolve;
        }),
      streamChatMessage,
    });
    renderApp(<AgentChatPanel client={client} historyOpen={true} />);

    await user.click(await screen.findByRole("button", { name: /Old Rules Chat/ }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "live");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByText("live")).toBeInTheDocument();
    resolveHistory({
      thread: {
        id: "thread-old",
        title: "Old Rules Chat",
        active_source_set_id: "rules-core",
        source_book_count: 1,
        created_at: "2026-06-06T00:00:00Z",
        updated_at: "2026-06-06T00:02:00Z",
      },
      source_book_ids: ["core-rules"],
      turns: [
        {
          user_message: {
            id: "m-old",
            thread_id: "thread-old",
            role: "user",
            content: "Loaded old question",
            created_at: "then",
          },
          assistant_message: {
            id: "a-old",
            thread_id: "thread-old",
            role: "assistant",
            content: "Loaded old answer",
            created_at: "then",
          },
          model_run: { ...modelRun("completed"), id: "run-old", thread_id: "thread-old" },
          citations: [],
        },
      ],
    });
    await expect(
      screen.findByText("Loaded old question", undefined, { timeout: 100 }),
    ).rejects.toThrow();
    finishStream();

    expect(await screen.findByText("Live answer.")).toBeInTheDocument();
    expect(screen.queryByText("Loaded old answer")).not.toBeInTheDocument();
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

  it("sends reader context and renders research trace events", async () => {
    const user = userEvent.setup();
    const readerContext = {
      active_book_id: "core-rules",
      active_pdf_page_number: 134,
      open_book_ids: ["core-rules"],
    };
    const streamChatMessage = vi.fn(async (threadId, options) => {
      options.onEvent({
        type: "accepted",
        user_message: {
          id: "m1",
          thread_id: threadId,
          role: "user",
          content: options.content,
          created_at: "now",
        },
        model_run: modelRun("retrieving"),
      });
      options.onEvent({
        type: "turn_decision",
        metadata: { turn_kind: "statline_lookup", answer_mode: "research" },
      });
      options.onEvent({
        type: "research_started",
        metadata: { resolved_query: "harpy statline" },
      });
      options.onEvent({
        type: "research_plan",
        metadata: { plan_summary: "Find cited Harpy statline evidence." },
      });
      options.onEvent({
        type: "tool_call",
        metadata: {
          tool_name: "search_library",
          arguments: { query: "harpy statline" },
        },
      });
      options.onEvent({
        type: "tool_result",
        metadata: {
          hit_count: 1,
          diagnostics: { vector_status: "ran" },
        },
      });
      options.onEvent({
        type: "evidence_validation",
        metadata: {
          evidence_status: "sufficient",
          accepted_hit_count: 1,
        },
      });
      options.onEvent({
        type: "finalizing",
        metadata: { decision_summary: "Requirements satisfied." },
      });
      options.onEvent({
        type: "completed",
        assistant_message: {
          id: "m2",
          thread_id: threadId,
          role: "assistant",
          content: "Harpy answer.",
          created_at: "later",
        },
        model_run: modelRun("completed"),
        citations: [],
      });
    });
    const client = chatClient({ streamChatMessage });
    renderApp(
      <AgentChatPanel
        client={client}
        historyOpen={false}
        readerContext={readerContext}
      />,
    );

    await user.type(screen.getByRole("textbox", { name: "Message" }), "harpy");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(streamChatMessage).toHaveBeenCalledWith(
      "thread-1",
      expect.objectContaining({
        content: "harpy",
        reader_context: readerContext,
      }),
    );
    const summary = (
      await screen.findAllByText("Evidence sufficient; 1 accepted")
    )[0];
    await user.click(summary);
    expect(screen.getByText("statline lookup; research")).toBeInTheDocument();
    expect(screen.getByText("Research started")).toBeInTheDocument();
    expect(screen.getByText("Research plan accepted")).toBeInTheDocument();
    expect(screen.getByText("Running hybrid search")).toBeInTheDocument();
    expect(
      screen.getByText("Tool returned 1 candidate(s); vector ran"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Answering from evidence").length).toBeGreaterThan(0);
  });

  it("does not render research trace chrome for direct turn decisions", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m-direct",
            thread_id: threadId,
            role: "user",
            content: options.content,
            created_at: "now",
          },
          model_run: modelRun("calling_model"),
        });
        options.onEvent({
          type: "turn_decision",
          metadata: { turn_kind: "conversation", answer_mode: "direct" },
        });
        options.onEvent({
          type: "completed",
          assistant_message: {
            id: "a-direct",
            thread_id: threadId,
            role: "assistant",
            content: "Hello.",
            created_at: "later",
          },
          model_run: modelRun("completed"),
          citations: [],
        });
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Hello.")).toBeInTheDocument();
    expect(screen.queryByText("conversation; research")).not.toBeInTheDocument();
    expect(screen.queryByText("Research turn")).not.toBeInTheDocument();
  });

  it("renders fallback research trace labels for non-search tool events", async () => {
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
          model_run: modelRun("retrieving"),
        });
        options.onEvent({ type: "research_started", metadata: {} });
        options.onEvent({
          type: "tool_call",
          metadata: {
            tool_name: "open_page",
            arguments: { pdf_page_number: 77 },
          },
        });
        options.onEvent({
          type: "tool_call",
          metadata: { tool_name: "open_page", arguments: {} },
        });
        options.onEvent({
          type: "tool_call",
          metadata: { tool_name: "lookup_source_object", arguments: {} },
        });
        options.onEvent({
          type: "tool_call",
          metadata: { tool_name: "roll_dice", arguments: [] },
        });
        options.onEvent({ type: "tool_call", metadata: {} });
        options.onEvent({ type: "tool_result", metadata: {} });
        options.onEvent({
          type: "evidence_validation",
          metadata: { evidence_status: "partial" },
        });
        options.onEvent({ type: "failed", error_message: "No evidence." });
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "trace");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    const summary = (await screen.findAllByText("Research failed"))[0];
    await user.click(summary);
    expect(screen.getByText("Research started")).toBeInTheDocument();
    expect(screen.getByText("Opening page 77")).toBeInTheDocument();
    expect(screen.getByText("Opening source page")).toBeInTheDocument();
    expect(screen.getByText("Inspecting source object")).toBeInTheDocument();
    expect(screen.getByText("Running roll_dice")).toBeInTheDocument();
    expect(screen.getByText("Running research tool")).toBeInTheDocument();
    expect(screen.getByText("Tool returned results")).toBeInTheDocument();
    expect(screen.getByText("Evidence partial")).toBeInTheDocument();
    expect(screen.getByText("No evidence.")).toBeInTheDocument();
  });

  it("renders validation reason counts without calling partial evidence sufficient", async () => {
    const user = userEvent.setup();
    const client = chatClient({
      async streamChatMessage(threadId, options) {
        options.onEvent({
          type: "accepted",
          user_message: {
            id: "m1",
            thread_id: threadId,
            role: "user",
            content: "trace counts",
            created_at: "now",
          },
          model_run: modelRun("retrieving"),
        });
        options.onEvent({
          type: "evidence_validation",
          metadata: {
            evidence_status: "partial",
            accepted_hit_count: 0,
            partial_hit_count: 1,
            rejected_hit_count: 2,
            reason_counts: {
              subject_mismatch: 1,
              missing_statline_fields: 1,
            },
          },
        });
        options.onEvent({ type: "failed", error_message: "Still missing evidence." });
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "trace counts");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    const summary = (await screen.findAllByText("Research failed"))[0];
    await user.click(summary);
    expect(
      screen.getByText(
        "Evidence partial; 0 accepted, 1 partial, 2 rejected (missing_statline_fields 1, subject_mismatch 1)",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Evidence sufficient; 0 accepted/i)).not.toBeInTheDocument();
  });

  it("ignores stream updates for unknown model run ids", async () => {
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
          model_run: { ...modelRun("calling_model"), id: "run-active" },
        });
        options.onEvent({
          type: "completed",
          assistant_message: {
            id: "m2",
            thread_id: threadId,
            role: "assistant",
            content: "Wrong target.",
            created_at: "later",
          },
          model_run: { ...modelRun("completed"), id: "run-other" },
          citations: [],
        });
      },
    });
    renderApp(<AgentChatPanel client={client} historyOpen={false} />);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "fear");
    await user.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("fear")).toBeInTheDocument();
    expect(screen.queryByText("Wrong target.")).not.toBeInTheDocument();
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
            {
              book_id: "core-rules",
              title: "Core Rules",
              category: "Core",
              page_id: "core-rules:132",
              page_number: 132,
              pdf_page_number: 132,
              page_label: "132",
              page_range_label: "132",
              snippet: "Critical hit",
              rank: 2,
              score: -2,
            },
            {
              book_id: "core-rules",
              title: "Core Rules",
              category: "Core",
              page_id: "core-rules:7",
              page_number: 7,
              pdf_page_number: 8,
              page_label: "7",
              snippet: "Critical hit",
              rank: 3,
              score: -3,
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
    expect(
      screen.getByRole("button", { name: "Open Core Rules printed page 132" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open Core Rules printed page 7" }),
    ).toBeInTheDocument();
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
    getRetrievalStatus: async () => ({
      books_total: 0,
      books_enabled: 0,
      page_text_indexed: 0,
      source_objects_indexed: 0,
      table_or_stat_indexed: 0,
      vectorized_current: 0,
      vectorized_enabled: 0,
      embedding_provider: "disabled",
      embedding_dimensions: null,
      vector_status: "disabled",
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

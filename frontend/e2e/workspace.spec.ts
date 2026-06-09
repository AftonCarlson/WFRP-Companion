import { expect, test, type Page } from "@playwright/test";

const coreBook = {
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
};

const sourceSetBook = {
  source_set_id: "rules-core",
  book_id: "core-rules",
  title: "Core Rules",
  category: "Rules / Core",
  enabled: true,
  search_ready: true,
};

function chatThread() {
  return {
    id: "thread-e2e",
    title: null,
    active_source_set_id: "rules-core",
    source_book_count: 1,
    created_at: "2026-06-09T00:00:00Z",
    updated_at: "2026-06-09T00:00:00Z",
  };
}

function modelRun(id: string, status: string) {
  return {
    id,
    thread_id: "thread-e2e",
    user_message_id: "message-e2e",
    assistant_message_id: status === "completed" ? "answer-e2e" : null,
    retrieval_run_id: "retrieval-e2e",
    retry_of_model_run_id: null,
    status,
    provider: "openai",
    model: "gpt-5.4-mini",
    provider_response_id: status === "completed" ? "response-e2e" : null,
    error_code: null,
    error_message: null,
    input_tokens: status === "completed" ? 10 : null,
    output_tokens: status === "completed" ? 3 : null,
    retryable: false,
  };
}

function chatStreamBody(content: string) {
  const isFollowup = content.includes("gors");
  const runId = isFollowup ? "run-gors" : "run-page";
  const answer = isFollowup
    ? "Follow-up hybrid search found gors."
    : "Page-aware lookup found p. 99.";
  const toolName = isFollowup ? "search_library" : "open_page";
  const toolArguments = isFollowup
    ? { query: "gor statline", intent: "statline_lookup", subject: "gors", limit: 8 }
    : {
        book_id: "core-rules",
        book_title_hint: null,
        printed_page_label: "99",
        pdf_page_number: null,
        subject_hint: null,
        intent: "rules_lookup",
      };
  const events = [
    {
      type: "accepted",
      thread: chatThread(),
      user_message: {
        id: "message-e2e",
        thread_id: "thread-e2e",
        role: "user",
        content,
        created_at: "2026-06-09T00:00:01Z",
      },
      model_run: modelRun(runId, "retrieving"),
      citations: [],
    },
    {
      type: "research_started",
      metadata: {
        resolved_query: isFollowup ? "gor statline" : "it's on pg 99 page 99",
      },
    },
    {
      type: "tool_call",
      metadata: {
        tool_name: toolName,
        arguments: toolArguments,
      },
    },
    {
      type: "tool_result",
      metadata: {
        hit_count: 1,
        diagnostics: {
          vector_status: isFollowup ? "ran" : "disabled",
        },
      },
    },
    {
      type: "evidence_validation",
      metadata: {
        evidence_status: "sufficient",
        accepted_hit_count: 1,
      },
    },
    { type: "delta", text_delta: answer },
    {
      type: "completed",
      thread: chatThread(),
      assistant_message: {
        id: "answer-e2e",
        thread_id: "thread-e2e",
        role: "assistant",
        content: answer,
        created_at: "2026-06-09T00:00:02Z",
      },
      model_run: modelRun(runId, "completed"),
      citations: [
        {
          rank: 1,
          book_id: "core-rules",
          title: "Core Rules",
          category: "Rules / Core",
          page_id: "core-rules:134",
          page_number: 134,
          pdf_page_number: 134,
          page_label: "99",
          page_range_label: "99",
          snippet: "Synthetic cited evidence.",
          score: 1,
        },
      ],
    },
  ];
  return events.map((event) => JSON.stringify(event)).join("\n") + "\n";
}

async function mockApi(page: Page) {
  const chatRequests: Array<Record<string, unknown>> = [];
  await page.route("**/api/health", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", database: "ready" }),
    });
  });
  await page.route("**/api/books", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ books: [coreBook] }),
    });
  });
  await page.route("**/api/retrieval/status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        books_total: 1,
        books_enabled: 1,
        page_text_indexed: 1,
        source_objects_indexed: 1,
        table_or_stat_indexed: 0,
        vectorized_current: 0,
        vectorized_enabled: 0,
        embedding_provider: "disabled",
        embedding_dimensions: null,
        vector_status: "disabled",
      }),
    });
  });
  await page.route("**/api/source-sets", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
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
    });
  });
  await page.route("**/api/source-sets/rules-core/books", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        source_set_id: "rules-core",
        books: [sourceSetBook],
      }),
    });
  });
  await page.route("**/api/search/exact?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        query: "critical hit",
        scope: {
          label: "Rules/Core",
          source_set_id: "rules-core",
          book_ids: ["core-rules"],
          all_books: false,
        },
        hits: [
          {
            rank: 1,
            book_id: "core-rules",
            title: "Core Rules",
            category: "Rules / Core",
            page_id: "core-rules:134",
            page_number: 134,
            pdf_page_number: 134,
            page_label: null,
            snippet: "Critical hit table result from indexed text.",
            score: 1.0,
          },
        ],
      }),
    });
  });
  await page.route("**/api/books/core-rules/pages/134/text", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        page_id: "core-rules:134",
        book_id: "core-rules",
        page_number: 134,
        page_label: "134",
        text: "Full page text from SQLite for the critical hit table.",
        text_chars: 57,
      }),
    });
  });
  await page.route("**/api/books/core-rules/pdf", async (route) => {
    await route.fulfill({
      contentType: "application/pdf",
      body: "%PDF-1.4\n%%EOF",
    });
  });
  await page.route("**/api/chat/threads", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ threads: [] }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(chatThread()),
    });
  });
  await page.route("**/api/chat/threads/thread-e2e/messages/stream", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    chatRequests.push(body);
    const content = typeof body.content === "string" ? body.content : "";
    await route.fulfill({
      contentType: "application/x-ndjson",
      body: chatStreamBody(content),
    });
  });
  return { chatRequests };
}

async function mockOverflowApi(page: Page) {
  await mockApi(page);
  await page.unroute("**/api/search/exact?**");
  await page.route("**/api/search/exact?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        query: "black knight",
        scope: {
          label: "Rules/Core",
          source_set_id: "rules-core",
          book_ids: ["core-rules"],
          all_books: false,
        },
        hits: Array.from({ length: 18 }, (_, index) => ({
          rank: index + 1,
          book_id: "core-rules",
          title: "Core Rules",
          category: "Rules / Core",
          page_id: `core-rules:${index + 1}`,
          page_number: index + 1,
          pdf_page_number: index + 1,
          page_label: null,
          snippet:
            "A deliberately long search snippet that should scroll inside the search results panel instead of increasing the page height.",
          score: 1.0,
        })),
      }),
    });
  });
}

test("workspace supports library, search, PDF tabs, and chat shell", async ({
  page,
}) => {
  const { chatRequests } = await mockApi(page);
  await page.goto("/");

  await expect(page.getByText("Core Rules")).toBeVisible();
  await expect(page.getByText("1 books enabled")).toBeVisible();
  await expect(
    page.getByText("Open a source from Library or Search."),
  ).toBeVisible();

  await page.getByRole("tab", { name: "Search" }).click();
  await page.getByRole("searchbox", { name: "Search book text" }).fill("critical hit");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("Critical hit table result")).toBeVisible();

  await page.getByRole("button", { name: "Show full text" }).click();
  await expect(page.getByText("Full page text from SQLite")).toBeVisible();

  await page.getByRole("button", { name: "Open Core Rules PDF page 134" }).click();
  await expect(page.getByRole("tab", { name: "Core Rules" })).toBeVisible();

  await page.getByRole("button", { name: "Open chat history" }).click();
  await expect(page.getByText("Chat history")).toBeVisible();
  await page.getByRole("textbox", { name: "Message" }).fill("it's on pg 99");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Page-aware lookup found p. 99.")).toBeVisible();
  await expect(
    page.locator("summary").filter({ hasText: "Evidence sufficient; 1 accepted" }),
  ).toBeVisible();

  await page.getByRole("textbox", { name: "Message" }).fill("same for gors");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Follow-up hybrid search found gors.")).toBeVisible();
  expect(chatRequests).toHaveLength(2);
  expect(chatRequests[0]).toMatchObject({
    content: "it's on pg 99",
    reader_context: {
      active_book_id: "core-rules",
      active_pdf_page_number: 134,
      open_book_ids: ["core-rules"],
    },
  });
  expect(chatRequests[1]).toMatchObject({
    content: "same for gors",
    reader_context: {
      active_book_id: "core-rules",
      active_pdf_page_number: 134,
      open_book_ids: ["core-rules"],
    },
  });
});

test("workspace panels contain their own vertical overflow", async ({ page }) => {
  await mockOverflowApi(page);
  await page.setViewportSize({ width: 1440, height: 760 });
  await page.goto("/");

  await page.getByRole("tab", { name: "Search" }).click();
  await page.getByRole("searchbox", { name: "Search book text" }).fill("black knight");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("18 hits")).toBeVisible();

  await page.getByRole("textbox", { name: "Message" }).fill(
    Array.from({ length: 20 }, () => "Describe this scene in detail.").join("\n"),
  );

  const measurements = await page.evaluate(() => {
    const scrollingElement = document.scrollingElement ?? document.documentElement;
    const searchResults = document.querySelector(".search-tab__results");
    const transcript = document.querySelector(".agent-chat__transcript");
    const composer = document.querySelector(".agent-chat__composer");
    const composerBox = composer?.getBoundingClientRect();
    const searchBox = searchResults?.getBoundingClientRect();
    const transcriptBox = transcript?.getBoundingClientRect();

    return {
      pageScrollHeight: scrollingElement.scrollHeight,
      viewportHeight: window.innerHeight,
      searchCanScroll:
        searchResults !== null &&
        searchResults.scrollHeight > searchResults.clientHeight,
      transcriptFits:
        transcriptBox !== undefined &&
        transcriptBox.top >= 0 &&
        transcriptBox.bottom <= window.innerHeight,
      composerFits:
        composerBox !== undefined &&
        composerBox.top >= 0 &&
        composerBox.bottom <= window.innerHeight,
      searchFits:
        searchBox !== undefined &&
        searchBox.top >= 0 &&
        searchBox.bottom <= window.innerHeight,
    };
  });

  expect(measurements.pageScrollHeight).toBeLessThanOrEqual(
    measurements.viewportHeight,
  );
  expect(measurements.searchCanScroll).toBe(true);
  expect(measurements.searchFits).toBe(true);
  expect(measurements.transcriptFits).toBe(true);
  expect(measurements.composerFits).toBe(true);
});

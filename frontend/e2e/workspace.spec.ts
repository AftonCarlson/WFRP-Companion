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

async function mockApi(page: Page) {
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
}

test("workspace supports library, search, PDF tabs, and chat shell", async ({
  page,
}) => {
  await mockApi(page);
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

  await page.getByRole("button", { name: "Open PDF page" }).click();
  await expect(page.getByRole("tab", { name: /Core Rules p\. 134/i })).toBeVisible();

  await page.getByRole("button", { name: "Open chat history" }).click();
  await expect(page.getByText("Chat history")).toBeVisible();
  await page.getByRole("textbox", { name: "Message" }).fill("What happens next?");
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(
    "What happens next?",
  );
});

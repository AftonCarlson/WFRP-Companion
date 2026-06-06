import { describe, expect, it } from "vitest";

import { groupByCategory, groupSearchHits, mergeLibraryRows } from "./grouping";

describe("grouping helpers", () => {
  it("merges source-set rows with readiness from book summaries", () => {
    const rows = mergeLibraryRows(
      [
        {
          id: "core-rules",
          title: "Core Rules",
          category: "Rules",
          relative_path: "Rules/Core.pdf",
          page_count: 10,
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
      [
        {
          source_set_id: "rules-core",
          book_id: "core-rules",
          title: "Core Rules",
          category: "Rules",
          enabled: true,
          search_ready: true,
        },
      ],
    );

    expect(rows[0]).toMatchObject({
      book_id: "core-rules",
      page_count: 10,
      reader_ready: true,
    });
  });

  it("groups library rows and search hits", () => {
    const libraryGroups = groupByCategory([
      {
        source_set_id: "rules-core",
        book_id: "core-rules",
        title: "Core Rules",
        category: "Rules",
        enabled: true,
        search_ready: true,
        page_count: 10,
        reader_ready: true,
        needs_attention: false,
      },
    ]);
    const searchGroups = groupSearchHits([
      {
        rank: 1,
        book_id: "core-rules",
        title: "Core Rules",
        category: "Rules",
        page_id: "core-rules:1",
        page_number: 1,
        pdf_page_number: 1,
        page_label: null,
        snippet: "critical hit",
        score: -1,
      },
      {
        rank: 2,
        book_id: "core-rules",
        title: "Core Rules",
        category: "Rules",
        page_id: "core-rules:2",
        page_number: 2,
        pdf_page_number: 2,
        page_label: null,
        snippet: "fumble",
        score: -0.5,
      },
    ]);

    expect(libraryGroups[0].category).toBe("Rules");
    expect(searchGroups[0].hits).toHaveLength(2);
  });

  it("uses safe defaults when a source-set row has no matching book summary", () => {
    const rows = mergeLibraryRows([], [
      {
        source_set_id: "rules-core",
        book_id: "missing",
        title: "Missing Book",
        category: "Rules",
        enabled: false,
        search_ready: false,
      },
    ]);

    expect(rows[0]).toMatchObject({
      page_count: 0,
      reader_ready: false,
      needs_attention: false,
    });
  });
});

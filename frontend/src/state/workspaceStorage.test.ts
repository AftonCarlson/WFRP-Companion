import { afterEach, describe, expect, it, vi } from "vitest";

import {
  defaultWorkspaceLayout,
  type PdfTab,
  setLeftTab,
  toggleLibraryCategory,
} from "./workspaceState";
import {
  loadWorkspaceLayout,
  saveWorkspaceLayout,
  WORKSPACE_STORAGE_KEY,
} from "./workspaceStorage";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("workspaceStorage", () => {
  it("round-trips valid workspace layout", () => {
    const layout = toggleLibraryCategory(
      setLeftTab(defaultWorkspaceLayout, "search"),
      "Rules / Core",
    );

    saveWorkspaceLayout(layout);

    expect(loadWorkspaceLayout()).toEqual(layout);
  });

  it("falls back to defaults for missing, malformed, or invalid values", () => {
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(WORKSPACE_STORAGE_KEY, "{bad json");
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify({ leftTab: "nope" }));
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(17));
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        ...defaultWorkspaceLayout,
        panels: null,
      }),
    );
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        ...defaultWorkspaceLayout,
        openPdfTabs: [{ id: "bad-tab" }],
      }),
    );
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        ...defaultWorkspaceLayout,
        collapsedLibraryCategories: [17],
      }),
    );
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        ...defaultWorkspaceLayout,
        openPdfTabs: [
          {
            id: "core-rules",
            bookId: "core-rules",
            title: "Core Rules",
            pageNumber: 1,
            zoom: 1,
            viewMode: "single",
          },
        ],
        activePdfTabId: "missing-tab",
      }),
    );
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        ...defaultWorkspaceLayout,
        panels: {},
      }),
    );
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);

    localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        ...defaultWorkspaceLayout,
        openPdfTabs: [null],
      }),
    );
    expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);
  });

  it("normalizes valid legacy PDF tabs without a stored view mode", () => {
    const legacyTab = {
      id: "core-rules",
      bookId: "core-rules",
      title: "Core Rules",
      pageNumber: 1,
      zoom: 1,
    };
    localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        ...defaultWorkspaceLayout,
        openPdfTabs: [legacyTab],
        activePdfTabId: "core-rules",
      }),
    );

    expect(loadWorkspaceLayout().openPdfTabs).toEqual([
      { ...legacyTab, viewMode: "single" },
    ]);
  });

  it("rejects invalid PDF tab field shapes", () => {
    const validTab: PdfTab = {
      id: "core-rules",
      bookId: "core-rules",
      title: "Core Rules",
      pageNumber: 1,
      zoom: 1,
      viewMode: "single",
    };
    const invalidTabs = [
      { ...validTab, id: 17 },
      { ...validTab, bookId: 17 },
      { ...validTab, title: 17 },
      { ...validTab, pageNumber: "1" },
      { ...validTab, pageNumber: Number.NaN },
      { ...validTab, zoom: "1" },
      { ...validTab, zoom: Number.NaN },
      { ...validTab, viewMode: "spread" },
    ];

    invalidTabs.forEach((tab) => {
      localStorage.setItem(
        WORKSPACE_STORAGE_KEY,
        JSON.stringify({
          ...defaultWorkspaceLayout,
          openPdfTabs: [tab],
        }),
      );

      expect(loadWorkspaceLayout()).toEqual(defaultWorkspaceLayout);
    });
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  defaultWorkspaceLayout,
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
});

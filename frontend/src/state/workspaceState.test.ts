import { describe, expect, it } from "vitest";

import {
  closePdfTab,
  defaultWorkspaceLayout,
  maximizePanel,
  openPdfTab,
  resizePanel,
  restorePanels,
  selectPdfTab,
  setLeftTab,
  setPdfTabPage,
  setPdfTabViewMode,
  setPdfTabZoom,
  toggleLibraryCategory,
  togglePanelCollapsed,
} from "./workspaceState";

describe("workspaceState", () => {
  it("keeps only one panel maximized", () => {
    const first = maximizePanel(defaultWorkspaceLayout, "left");
    const second = maximizePanel(first, "reader");

    expect(second.panels.left.maximized).toBe(false);
    expect(second.panels.reader.maximized).toBe(true);
    expect(second.panels.agent.maximized).toBe(false);
  });

  it("collapses and restores panels", () => {
    const collapsed = togglePanelCollapsed(defaultWorkspaceLayout, "agent");
    const restored = restorePanels(collapsed);

    expect(collapsed.panels.agent.collapsed).toBe(true);
    expect(restored.panels.agent.collapsed).toBe(false);
  });

  it("clamps resizable side panels", () => {
    expect(resizePanel(defaultWorkspaceLayout, "left", 100).panels.left.size).toBe(
      220,
    );
    expect(
      resizePanel(defaultWorkspaceLayout, "agent", 900).panels.agent.size,
    ).toBe(760);
    expect(resizePanel(defaultWorkspaceLayout, "reader", 900)).toEqual(
      defaultWorkspaceLayout,
    );
  });

  it("tracks left tab and category collapse state", () => {
    const searched = setLeftTab(defaultWorkspaceLayout, "search");
    const collapsed = toggleLibraryCategory(searched, "Rules / Core");
    const expanded = toggleLibraryCategory(collapsed, "Rules / Core");

    expect(searched.leftTab).toBe("search");
    expect(collapsed.collapsedLibraryCategories).toEqual(["Rules / Core"]);
    expect(expanded.collapsedLibraryCategories).toEqual([]);
  });

  it("opens one PDF tab per source and updates exact page jumps", () => {
    const opened = openPdfTab(defaultWorkspaceLayout, {
      bookId: "core-rules",
      title: "Core Rules",
      pageNumber: 1,
    });
    const jumped = openPdfTab(opened, {
      bookId: "core-rules",
      title: "Core Rules",
      pageNumber: 134,
    });

    expect(jumped.openPdfTabs).toHaveLength(1);
    expect(jumped.openPdfTabs[0].pageNumber).toBe(134);
    expect(jumped.activePdfTabId).toBe("core-rules");
  });

  it("updates and closes PDF tabs", () => {
    const opened = openPdfTab(defaultWorkspaceLayout, {
      bookId: "core-rules",
      title: "Core Rules",
    });
    const second = openPdfTab(opened, {
      bookId: "bestiary",
      title: "Old World Bestiary",
    });
    const paged = setPdfTabPage(second, "core-rules", 0);
    const zoomed = setPdfTabZoom(paged, "core-rules", 4);
    const closedInactive = closePdfTab(zoomed, "core-rules");
    const closed = closePdfTab(closedInactive, "bestiary");

    expect(paged.openPdfTabs[0].pageNumber).toBe(1);
    expect(zoomed.openPdfTabs[0].zoom).toBe(3);
    expect(closedInactive.activePdfTabId).toBe("bestiary");
    expect(closedInactive.openPdfTabs).toHaveLength(1);
    expect(closed.openPdfTabs).toHaveLength(0);
    expect(closed.activePdfTabId).toBeNull();
  });

  it("keeps an existing PDF tab page when reopened without a page number", () => {
    const opened = openPdfTab(defaultWorkspaceLayout, {
      bookId: "core-rules",
      title: "Core Rules",
      pageNumber: 134,
    });
    const reopened = openPdfTab(opened, {
      bookId: "core-rules",
      title: "Core Rules Revised",
    });

    expect(reopened.openPdfTabs).toHaveLength(1);
    expect(reopened.openPdfTabs[0].pageNumber).toBe(134);
    expect(reopened.openPdfTabs[0].title).toBe("Core Rules Revised");
    expect(reopened.openPdfTabs[0].viewMode).toBe("single");
  });

  it("updates PDF tab view mode", () => {
    const opened = openPdfTab(defaultWorkspaceLayout, {
      bookId: "core-rules",
      title: "Core Rules",
    });
    const spread = setPdfTabViewMode(opened, "core-rules", "two-page");

    expect(spread.openPdfTabs[0].viewMode).toBe("two-page");
    expect(setPdfTabViewMode(opened, "missing", "two-page")).toEqual(opened);
  });

  it("can force explicit PDF page jumps back to single-page view", () => {
    const opened = openPdfTab(defaultWorkspaceLayout, {
      bookId: "core-rules",
      title: "Core Rules",
      pageNumber: 131,
    });
    const spread = setPdfTabViewMode(opened, "core-rules", "two-page");
    const jumped = openPdfTab(spread, {
      bookId: "core-rules",
      title: "Core Rules",
      pageNumber: 132,
      viewMode: "single",
    });

    expect(jumped.openPdfTabs[0].pageNumber).toBe(132);
    expect(jumped.openPdfTabs[0].viewMode).toBe("single");
  });

  it("ignores tab mutations for unknown tabs", () => {
    const opened = openPdfTab(defaultWorkspaceLayout, {
      bookId: "core-rules",
      title: "Core Rules",
    });

    expect(selectPdfTab(opened, "missing")).toBe(opened);
    expect(setPdfTabPage(opened, "missing", 7)).toEqual(opened);
    expect(setPdfTabZoom(opened, "missing", 2)).toEqual(opened);
  });
});

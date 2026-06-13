export type LeftTab = "library" | "search" | "review";
export type PanelId = "left" | "reader" | "agent";
export type PdfViewMode = "single" | "two-page";

export type PanelLayout = {
  size: number;
  collapsed: boolean;
  maximized: boolean;
};

export type PdfTab = {
  id: string;
  bookId: string;
  title: string;
  pageNumber: number;
  zoom: number;
  viewMode: PdfViewMode;
};

export type PdfTabInput = {
  bookId: string;
  title: string;
  pageNumber?: number;
  viewMode?: PdfViewMode;
};

export type WorkspaceLayout = {
  leftTab: LeftTab;
  panels: Record<PanelId, PanelLayout>;
  collapsedLibraryCategories: string[];
  openPdfTabs: PdfTab[];
  activePdfTabId: string | null;
};

export const PANEL_SIZE_MIN = 220;
export const PANEL_SIZE_MAX = 760;

export const defaultWorkspaceLayout: WorkspaceLayout = {
  leftTab: "library",
  panels: {
    left: { size: 360, collapsed: false, maximized: false },
    reader: { size: 1, collapsed: false, maximized: false },
    agent: { size: 330, collapsed: false, maximized: false },
  },
  collapsedLibraryCategories: [],
  openPdfTabs: [],
  activePdfTabId: null,
};

const panelIds: PanelId[] = ["left", "reader", "agent"];

function clampSize(size: number) {
  return Math.max(PANEL_SIZE_MIN, Math.min(PANEL_SIZE_MAX, Math.round(size)));
}

function copy(layout: WorkspaceLayout): WorkspaceLayout {
  return {
    ...layout,
    panels: {
      left: { ...layout.panels.left },
      reader: { ...layout.panels.reader },
      agent: { ...layout.panels.agent },
    },
    collapsedLibraryCategories: [...layout.collapsedLibraryCategories],
    openPdfTabs: layout.openPdfTabs.map((tab) => ({ ...tab })),
  };
}

export function resizePanel(
  layout: WorkspaceLayout,
  panelId: PanelId,
  nextSize: number,
): WorkspaceLayout {
  const next = copy(layout);
  if (panelId === "reader") {
    return next;
  }
  next.panels[panelId].size = clampSize(nextSize);
  return next;
}

export function togglePanelCollapsed(
  layout: WorkspaceLayout,
  panelId: PanelId,
): WorkspaceLayout {
  const next = copy(layout);
  next.panels[panelId].collapsed = !next.panels[panelId].collapsed;
  next.panels[panelId].maximized = false;
  return next;
}

export function maximizePanel(
  layout: WorkspaceLayout,
  panelId: PanelId,
): WorkspaceLayout {
  const next = copy(layout);
  const shouldMaximize = !next.panels[panelId].maximized;
  for (const id of panelIds) {
    next.panels[id].maximized = id === panelId ? shouldMaximize : false;
  }
  return next;
}

export function restorePanels(layout: WorkspaceLayout): WorkspaceLayout {
  const next = copy(layout);
  for (const id of panelIds) {
    next.panels[id].collapsed = false;
    next.panels[id].maximized = false;
  }
  return next;
}

export function setLeftTab(
  layout: WorkspaceLayout,
  leftTab: LeftTab,
): WorkspaceLayout {
  return { ...copy(layout), leftTab };
}

export function toggleLibraryCategory(
  layout: WorkspaceLayout,
  category: string,
): WorkspaceLayout {
  const next = copy(layout);
  const exists = next.collapsedLibraryCategories.includes(category);
  next.collapsedLibraryCategories = exists
    ? next.collapsedLibraryCategories.filter((item) => item !== category)
    : [...next.collapsedLibraryCategories, category];
  return next;
}

export function openPdfTab(
  layout: WorkspaceLayout,
  input: PdfTabInput,
): WorkspaceLayout {
  const next = copy(layout);
  const existing = next.openPdfTabs.find((tab) => tab.bookId === input.bookId);
  if (existing) {
    existing.pageNumber = input.pageNumber ?? existing.pageNumber;
    existing.title = input.title;
    existing.viewMode = input.viewMode ?? existing.viewMode;
    next.activePdfTabId = existing.id;
    return next;
  }

  const tab: PdfTab = {
    id: input.bookId,
    bookId: input.bookId,
    title: input.title,
    pageNumber: input.pageNumber ?? 1,
    zoom: 1,
    viewMode: input.viewMode ?? "single",
  };
  next.openPdfTabs.push(tab);
  next.activePdfTabId = tab.id;
  return next;
}

export function closePdfTab(
  layout: WorkspaceLayout,
  tabId: string,
): WorkspaceLayout {
  const next = copy(layout);
  const closingIndex = next.openPdfTabs.findIndex((tab) => tab.id === tabId);
  next.openPdfTabs = next.openPdfTabs.filter((tab) => tab.id !== tabId);
  if (next.activePdfTabId === tabId) {
    next.activePdfTabId =
      next.openPdfTabs[Math.max(0, closingIndex - 1)]?.id ?? null;
  }
  return next;
}

export function setPdfTabPage(
  layout: WorkspaceLayout,
  tabId: string,
  pageNumber: number,
): WorkspaceLayout {
  const next = copy(layout);
  const tab = next.openPdfTabs.find((item) => item.id === tabId);
  if (tab) {
    tab.pageNumber = Math.max(1, Math.round(pageNumber));
  }
  return next;
}

export function setPdfTabZoom(
  layout: WorkspaceLayout,
  tabId: string,
  zoom: number,
): WorkspaceLayout {
  const next = copy(layout);
  const tab = next.openPdfTabs.find((item) => item.id === tabId);
  if (tab) {
    tab.zoom = Math.max(0.4, Math.min(3, Number(zoom.toFixed(2))));
  }
  return next;
}

export function setPdfTabViewMode(
  layout: WorkspaceLayout,
  tabId: string,
  viewMode: PdfViewMode,
): WorkspaceLayout {
  const next = copy(layout);
  const tab = next.openPdfTabs.find((item) => item.id === tabId);
  if (tab) {
    tab.viewMode = viewMode;
  }
  return next;
}

export function selectPdfTab(
  layout: WorkspaceLayout,
  tabId: string,
): WorkspaceLayout {
  if (!layout.openPdfTabs.some((tab) => tab.id === tabId)) {
    return layout;
  }
  return { ...copy(layout), activePdfTabId: tabId };
}

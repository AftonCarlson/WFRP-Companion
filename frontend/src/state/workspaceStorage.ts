import {
  defaultWorkspaceLayout,
  type PanelId,
  type PanelLayout,
  type PdfTab,
  type WorkspaceLayout,
} from "./workspaceState";

export const WORKSPACE_STORAGE_KEY = "wfrp-companion.workspace-layout.v1";

function isWorkspaceLayout(value: unknown): value is WorkspaceLayout {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<WorkspaceLayout>;
  return (
    (candidate.leftTab === "library" || candidate.leftTab === "search") &&
    isPanelRecord(candidate.panels) &&
    isStringArray(candidate.collapsedLibraryCategories) &&
    Array.isArray(candidate.openPdfTabs) &&
    candidate.openPdfTabs.every(isPdfTab) &&
    (typeof candidate.activePdfTabId === "string" ||
      candidate.activePdfTabId === null) &&
    (candidate.activePdfTabId === null ||
      candidate.openPdfTabs.some((tab) => tab.id === candidate.activePdfTabId))
  );
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isPanelLayout(value: unknown): value is PanelLayout {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<PanelLayout>;
  return (
    typeof candidate.size === "number" &&
    Number.isFinite(candidate.size) &&
    typeof candidate.collapsed === "boolean" &&
    typeof candidate.maximized === "boolean"
  );
}

function isPanelRecord(value: unknown): value is WorkspaceLayout["panels"] {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<Record<PanelId, unknown>>;
  return (
    isPanelLayout(candidate.left) &&
    isPanelLayout(candidate.reader) &&
    isPanelLayout(candidate.agent)
  );
}

function isPdfTab(value: unknown): value is PdfTab {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<PdfTab>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.bookId === "string" &&
    typeof candidate.title === "string" &&
    typeof candidate.pageNumber === "number" &&
    Number.isFinite(candidate.pageNumber) &&
    typeof candidate.zoom === "number" &&
    Number.isFinite(candidate.zoom) &&
    (candidate.viewMode === undefined ||
      candidate.viewMode === "single" ||
      candidate.viewMode === "two-page")
  );
}

export function loadWorkspaceLayout(
  storage: Storage = localStorage,
): WorkspaceLayout {
  const raw = storage.getItem(WORKSPACE_STORAGE_KEY);
  if (raw === null) {
    return defaultWorkspaceLayout;
  }

  try {
    const parsed = JSON.parse(raw) as unknown;
    return isWorkspaceLayout(parsed)
      ? normalizeWorkspaceLayout(parsed)
      : defaultWorkspaceLayout;
  } catch {
    return defaultWorkspaceLayout;
  }
}

function normalizeWorkspaceLayout(layout: WorkspaceLayout): WorkspaceLayout {
  return {
    ...layout,
    openPdfTabs: layout.openPdfTabs.map((tab) => ({
      ...tab,
      viewMode: tab.viewMode ?? "single",
    })),
  };
}

export function saveWorkspaceLayout(
  layout: WorkspaceLayout,
  storage: Storage = localStorage,
) {
  storage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(layout));
}

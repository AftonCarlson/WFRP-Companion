import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  defaultWorkspaceLayout,
  closePdfTab,
  maximizePanel,
  openPdfTab,
  PANEL_SIZE_MAX,
  PANEL_SIZE_MIN,
  resizePanel,
  selectPdfTab,
  setLeftTab,
  setPdfTabPage,
  setPdfTabZoom,
  toggleLibraryCategory,
  togglePanelCollapsed,
  type PdfTabInput,
  type LeftTab,
  type PanelId,
  type WorkspaceLayout,
} from "../state/workspaceState";
import {
  loadWorkspaceLayout,
  saveWorkspaceLayout,
} from "../state/workspaceStorage";
import { PanelDivider } from "./PanelDivider";
import { RestoreRail } from "./RestoreRail";
import { TopBar } from "./TopBar";
import { ViewMenu } from "./ViewMenu";
import { WorkspacePanel } from "./WorkspacePanel";
import "./AppShell.css";

export type AppShellProps = {
  agent: (context: AppShellContext) => ReactNode;
  enabledBookCount: number;
  error?: string | null;
  left: (context: AppShellContext) => ReactNode;
  loading?: boolean;
  reader: (context: AppShellContext) => ReactNode;
};

export type AppShellContext = {
  closePdfTab: (tabId: string) => void;
  layout: WorkspaceLayout;
  openPdfTab: (input: PdfTabInput) => void;
  selectPdfTab: (tabId: string) => void;
  setLeftTab: (leftTab: LeftTab) => void;
  setPdfTabPage: (tabId: string, pageNumber: number) => void;
  setPdfTabZoom: (tabId: string, zoom: number) => void;
  toggleLibraryCategory: (category: string) => void;
};

export function AppShell({
  agent,
  enabledBookCount,
  error,
  left,
  loading = false,
  reader,
}: AppShellProps) {
  const [layout, setLayout] = useState<WorkspaceLayout>(() =>
    loadWorkspaceLayout(),
  );
  const [viewMenuOpen, setViewMenuOpen] = useState(false);

  useEffect(() => {
    saveWorkspaceLayout(layout);
  }, [layout]);

  const maximizedPanel = (Object.keys(layout.panels) as PanelId[]).find(
    (panelId) => layout.panels[panelId].maximized,
  );

  const gridTemplateColumns = useMemo(() => {
    if (maximizedPanel) {
      return "1fr";
    }
    const leftWidth = layout.panels.left.collapsed
      ? "42px"
      : `${layout.panels.left.size}px`;
    const agentWidth = layout.panels.agent.collapsed
      ? "42px"
      : `${layout.panels.agent.size}px`;
    return `${leftWidth} 8px minmax(360px, 1fr) 8px ${agentWidth}`;
  }, [layout, maximizedPanel]);

  function updateLayout(next: WorkspaceLayout) {
    setLayout(next);
  }

  function focusLeftTab(leftTab: LeftTab) {
    updateLayout(setLeftTab(restoreIfCollapsed(layout, "left"), leftTab));
  }

  const context: AppShellContext = {
    closePdfTab: (tabId) => updateLayout(closePdfTab(layout, tabId)),
    layout,
    openPdfTab: (input) => updateLayout(openPdfTab(layout, input)),
    selectPdfTab: (tabId) => updateLayout(selectPdfTab(layout, tabId)),
    setLeftTab: focusLeftTab,
    setPdfTabPage: (tabId, pageNumber) =>
      updateLayout(setPdfTabPage(layout, tabId, pageNumber)),
    setPdfTabZoom: (tabId, zoom) => updateLayout(setPdfTabZoom(layout, tabId, zoom)),
    toggleLibraryCategory: (category) =>
      updateLayout(toggleLibraryCategory(layout, category)),
  };

  function panel(panelId: PanelId, title: string, children: ReactNode) {
    const panelLayout = layout.panels[panelId];
    if (maximizedPanel && maximizedPanel !== panelId) {
      return null;
    }
    if (panelLayout.collapsed) {
      return (
        <RestoreRail
          label={title}
          onRestore={() => updateLayout(togglePanelCollapsed(layout, panelId))}
        />
      );
    }
    return (
      <WorkspacePanel
        collapsed={panelLayout.collapsed}
        maximized={panelLayout.maximized}
        onCollapse={() => updateLayout(togglePanelCollapsed(layout, panelId))}
        onMaximize={() => updateLayout(maximizePanel(layout, panelId))}
        title={title}
      >
        {children}
      </WorkspacePanel>
    );
  }

  return (
    <main className="app-shell" aria-label="WFRP Companion workspace">
      <div className="app-shell__top">
        <TopBar
          enabledBookCount={enabledBookCount}
          onFocusLibrary={() => focusLeftTab("library")}
          onToggleViewMenu={() => setViewMenuOpen((value) => !value)}
          viewMenuOpen={viewMenuOpen}
        />
        {viewMenuOpen ? (
          <ViewMenu
            onResetLayout={() => {
              setLayout(defaultWorkspaceLayout);
              setViewMenuOpen(false);
            }}
          />
        ) : null}
      </div>
      {loading ? <div className="app-banner">Loading local library...</div> : null}
      {error ? <div className="app-banner app-banner--error">{error}</div> : null}
      <div className="workspace-grid" style={{ gridTemplateColumns }}>
        {panel("left", "Library / Search", left(context))}
        {maximizedPanel ? null : (
          <PanelDivider
            label="Resize Library and PDF Reader"
            onResize={(delta) =>
              updateLayout(
                resizePanel(layout, "left", layout.panels.left.size + delta),
              )
            }
            valueMax={PANEL_SIZE_MAX}
            valueMin={PANEL_SIZE_MIN}
            valueNow={layout.panels.left.size}
          />
        )}
        {panel("reader", "PDF Reader", reader(context))}
        {maximizedPanel ? null : (
          <PanelDivider
            label="Resize PDF Reader and Agent Chat"
            onResize={(delta) =>
              updateLayout(
                resizePanel(layout, "agent", layout.panels.agent.size - delta),
              )
            }
            valueMax={PANEL_SIZE_MAX}
            valueMin={PANEL_SIZE_MIN}
            valueNow={layout.panels.agent.size}
          />
        )}
        {panel("agent", "Agent Chat", agent(context))}
      </div>
    </main>
  );
}

function restoreIfCollapsed(
  layout: WorkspaceLayout,
  panelId: PanelId,
): WorkspaceLayout {
  return layout.panels[panelId].collapsed
    ? togglePanelCollapsed(layout, panelId)
    : layout;
}

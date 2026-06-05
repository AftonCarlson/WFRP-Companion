import { Maximize2, Minimize2, PanelLeftClose } from "lucide-react";
import type { ReactNode } from "react";

export type WorkspacePanelProps = {
  children: ReactNode;
  collapsed: boolean;
  headerTools?: ReactNode;
  maximized: boolean;
  onCollapse: () => void;
  onMaximize: () => void;
  title: string;
};

export function WorkspacePanel({
  children,
  collapsed,
  headerTools,
  maximized,
  onCollapse,
  onMaximize,
  title,
}: WorkspacePanelProps) {
  if (collapsed) {
    return null;
  }

  return (
    <section className="workspace-panel" aria-label={title}>
      <header className="workspace-panel__header">
        <strong className="workspace-panel__title">{title}</strong>
        {headerTools ? (
          <div className="workspace-panel__header-tools">{headerTools}</div>
        ) : null}
        <div className="workspace-panel__controls">
          <button type="button" onClick={onCollapse} aria-label={`Collapse ${title}`}>
            <PanelLeftClose aria-hidden="true" size={15} />
          </button>
          <button
            type="button"
            onClick={onMaximize}
            aria-label={maximized ? `Restore ${title}` : `Maximize ${title}`}
          >
            {maximized ? (
              <Minimize2 aria-hidden="true" size={15} />
            ) : (
              <Maximize2 aria-hidden="true" size={15} />
            )}
          </button>
        </div>
      </header>
      <div className="workspace-panel__body">{children}</div>
    </section>
  );
}

import { Minus, Plus, RotateCcw, X } from "lucide-react";
import type { ChangeEvent } from "react";

import type { PdfTab } from "../../state/workspaceState";
import { PdfCanvas } from "./PdfCanvas";
import "./PdfReaderPanel.css";

export type PdfReaderPanelProps = {
  activeTabId: string | null;
  onCloseTab: (tabId: string) => void;
  onSelectTab: (tabId: string) => void;
  onSetPage: (tabId: string, pageNumber: number) => void;
  onSetZoom: (tabId: string, zoom: number) => void;
  openTabs: PdfTab[];
};

export function PdfReaderPanel({
  activeTabId,
  onCloseTab,
  onSelectTab,
  onSetPage,
  onSetZoom,
  openTabs,
}: PdfReaderPanelProps) {
  const activeTab =
    openTabs.find((tab) => tab.id === activeTabId) ?? openTabs[0] ?? null;

  if (!activeTab) {
    return (
      <div className="pdf-reader pdf-reader--empty">
        <p>Open a source from Library or Search.</p>
      </div>
    );
  }

  function setPageFromInput(event: ChangeEvent<HTMLInputElement>) {
    onSetPage(activeTab.id, Number(event.target.value));
  }

  return (
    <div className="pdf-reader">
      <div className="pdf-reader__tabs" role="tablist" aria-label="Open PDF sources">
        {openTabs.map((tab) => (
          <button
            aria-controls={pdfPanelId(tab.id)}
            aria-selected={tab.id === activeTab.id}
            className="pdf-reader__tab"
            id={pdfTabId(tab.id)}
            key={tab.id}
            onClick={() => onSelectTab(tab.id)}
            role="tab"
            tabIndex={tab.id === activeTab.id ? 0 : -1}
            type="button"
          >
            <span>{tab.title} p. {tab.pageNumber}</span>
          </button>
        ))}
      </div>
      <div className="pdf-reader__tab-actions" aria-label="PDF tab actions">
        {openTabs.map((tab) => (
          <button
            aria-label={`Close ${tab.title}`}
            className="pdf-reader__tab-close"
            key={tab.id}
            onClick={() => onCloseTab(tab.id)}
            type="button"
          >
            <X aria-hidden="true" size={14} />
          </button>
        ))}
      </div>
      <div className="pdf-reader__toolbar" aria-label="PDF controls">
        <button
          aria-label="Previous page"
          disabled={activeTab.pageNumber <= 1}
          onClick={() => onSetPage(activeTab.id, activeTab.pageNumber - 1)}
          type="button"
        >
          <Minus aria-hidden="true" size={14} />
        </button>
        <label>
          <span>Page</span>
          <input
            aria-label="Page number"
            min={1}
            onChange={setPageFromInput}
            type="number"
            value={activeTab.pageNumber}
          />
        </label>
        <button
          aria-label="Next page"
          onClick={() => onSetPage(activeTab.id, activeTab.pageNumber + 1)}
          type="button"
        >
          <Plus aria-hidden="true" size={14} />
        </button>
        <button
          aria-label="Zoom out"
          onClick={() => onSetZoom(activeTab.id, activeTab.zoom - 0.1)}
          type="button"
        >
          <Minus aria-hidden="true" size={14} />
        </button>
        <span className="pdf-reader__zoom">{Math.round(activeTab.zoom * 100)}%</span>
        <button
          aria-label="Zoom in"
          onClick={() => onSetZoom(activeTab.id, activeTab.zoom + 0.1)}
          type="button"
        >
          <Plus aria-hidden="true" size={14} />
        </button>
        <button
          aria-label="Fit width"
          onClick={() => onSetZoom(activeTab.id, 1)}
          type="button"
        >
          <RotateCcw aria-hidden="true" size={14} />
        </button>
      </div>
      <div
        aria-labelledby={pdfTabId(activeTab.id)}
        className="pdf-reader__body"
        id={pdfPanelId(activeTab.id)}
        role="tabpanel"
      >
        <PdfCanvas tab={activeTab} />
      </div>
    </div>
  );
}

function safeDomId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-");
}

function pdfTabId(tabId: string) {
  return `pdf-tab-${safeDomId(tabId)}`;
}

function pdfPanelId(tabId: string) {
  return `pdf-panel-${safeDomId(tabId)}`;
}

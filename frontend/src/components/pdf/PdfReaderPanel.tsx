import { Columns2, Minus, Plus, RotateCcw, Square, X } from "lucide-react";
import type { ChangeEvent } from "react";
import { useState } from "react";

import { nextPdfPage, previousPdfPage } from "../../lib/pdfPages";
import type { PdfTab, PdfViewMode } from "../../state/workspaceState";
import { PdfCanvas } from "./PdfCanvas";
import "./PdfReaderPanel.css";

export type PdfReaderPanelProps = {
  activeTabId: string | null;
  onCloseTab: (tabId: string) => void;
  onSelectTab: (tabId: string) => void;
  onSetPage: (tabId: string, pageNumber: number) => void;
  openTabs: PdfTab[];
};

export type PdfReaderControlsProps = {
  activeTabId: string | null;
  onSetPage: (tabId: string, pageNumber: number) => void;
  onSetViewMode: (tabId: string, viewMode: PdfViewMode) => void;
  onSetZoom: (tabId: string, zoom: number) => void;
  openTabs: PdfTab[];
};

export function PdfReaderControls({
  activeTabId,
  onSetPage,
  onSetViewMode,
  onSetZoom,
  openTabs,
}: PdfReaderControlsProps) {
  const activeTab =
    openTabs.find((tab) => tab.id === activeTabId) ?? openTabs[0] ?? null;

  if (!activeTab) {
    return null;
  }

  function setPageFromInput(event: ChangeEvent<HTMLInputElement>) {
    onSetPage(activeTab.id, Number(event.target.value));
  }

  return (
    <div className="pdf-reader__controls" aria-label="PDF controls">
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
      <div className="pdf-reader__view-toggle" role="group">
        <button
          aria-label="Single-page view"
          aria-pressed={activeTab.viewMode === "single"}
          onClick={() => onSetViewMode(activeTab.id, "single")}
          type="button"
        >
          <Square aria-hidden="true" size={14} />
        </button>
        <button
          aria-label="Two-page view"
          aria-pressed={activeTab.viewMode === "two-page"}
          onClick={() => onSetViewMode(activeTab.id, "two-page")}
          type="button"
        >
          <Columns2 aria-hidden="true" size={14} />
        </button>
      </div>
      <button
        aria-label="Zoom out"
        onClick={() => onSetZoom(activeTab.id, activeTab.zoom - 0.1)}
        type="button"
      >
        <Minus aria-hidden="true" size={14} />
      </button>
      <span className="pdf-reader__zoom">
        {Math.round(activeTab.zoom * 100)}%
      </span>
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
  );
}

export function PdfReaderPanel({
  activeTabId,
  onCloseTab,
  onSelectTab,
  onSetPage,
  openTabs,
}: PdfReaderPanelProps) {
  const [pageCounts, setPageCounts] = useState<Record<string, number>>({});
  const activeTab =
    openTabs.find((tab) => tab.id === activeTabId) ?? openTabs[0] ?? null;

  if (!activeTab) {
    return (
      <div className="pdf-reader pdf-reader--empty">
        <p>Open a source from Library or Search.</p>
      </div>
    );
  }

  const activePageCount =
    pageCounts[activeTab.id] ?? activeTab.pageNumber + 1000;
  const displayedPage = clampPdfPage(activeTab.pageNumber, activePageCount);
  const displayedTab =
    displayedPage === activeTab.pageNumber
      ? activeTab
      : { ...activeTab, pageNumber: displayedPage };
  const previousPage = previousPdfPage(
    displayedPage,
    activePageCount,
    activeTab.viewMode,
  );
  const nextPage = nextPdfPage(
    displayedPage,
    activePageCount,
    activeTab.viewMode,
  );

  return (
    <div className="pdf-reader">
      <div
        className="pdf-reader__tabs"
      >
        <div
          aria-label="Open PDF sources"
          className="pdf-reader__tablist"
          role="tablist"
        >
          {openTabs.map((tab) => (
            <button
              aria-controls={pdfPanelId(tab.id)}
              aria-selected={tab.id === activeTab.id}
              className={`pdf-reader__tab${
                tab.id === activeTab.id ? " pdf-reader__tab--active" : ""
              }`}
              id={pdfTabId(tab.id)}
              key={tab.id}
              onClick={() => onSelectTab(tab.id)}
              role="tab"
              tabIndex={tab.id === activeTab.id ? 0 : -1}
              type="button"
            >
              <span>{tab.title}</span>
            </button>
          ))}
        </div>
        <div className="pdf-reader__tab-close-row">
          {openTabs.map((tab) => (
            <div className="pdf-reader__tab-close-slot" key={tab.id}>
              <button
                aria-label={`Close ${tab.title}`}
                className="pdf-reader__tab-close"
                onClick={() => onCloseTab(tab.id)}
                type="button"
              >
                <X aria-hidden="true" size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>
      <div
        aria-labelledby={pdfTabId(activeTab.id)}
        className="pdf-reader__body"
        id={pdfPanelId(activeTab.id)}
        role="tabpanel"
      >
        <button
          aria-label="Previous page"
          className="pdf-reader__side-nav"
          disabled={previousPage === displayedPage}
          onClick={() => onSetPage(activeTab.id, previousPage)}
          type="button"
        >
          <span aria-hidden="true">&lt;</span>
        </button>
        <div className="pdf-reader__viewport">
          <PdfCanvas
            onDocumentLoaded={(pageCount) => {
              setPageCounts((currentCounts) => ({
                ...currentCounts,
                [activeTab.id]: pageCount,
              }));
              const nextDisplayedPage = clampPdfPage(
                activeTab.pageNumber,
                pageCount,
              );
              if (nextDisplayedPage !== activeTab.pageNumber) {
                onSetPage(activeTab.id, nextDisplayedPage);
              }
            }}
            tab={displayedTab}
          />
        </div>
        <button
          aria-label="Next page"
          className="pdf-reader__side-nav"
          disabled={nextPage === displayedPage}
          onClick={() => onSetPage(activeTab.id, nextPage)}
          type="button"
        >
          <span aria-hidden="true">&gt;</span>
        </button>
      </div>
    </div>
  );
}

function safeDomId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-");
}

function clampPdfPage(pageNumber: number, pageCount: number) {
  return Math.max(1, Math.min(Math.round(pageNumber), Math.max(1, pageCount)));
}

function pdfTabId(tabId: string) {
  return `pdf-tab-${safeDomId(tabId)}`;
}

function pdfPanelId(tabId: string) {
  return `pdf-panel-${safeDomId(tabId)}`;
}

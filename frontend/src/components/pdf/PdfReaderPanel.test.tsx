import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PdfTab } from "../../state/workspaceState";
import { renderApp } from "../../test/render";
import { PdfReaderControls, PdfReaderPanel } from "./PdfReaderPanel";

vi.mock("./PdfCanvas", () => ({
  PdfCanvas: ({
    onDocumentLoaded,
    tab,
  }: {
    onDocumentLoaded?: (pageCount: number) => void;
    tab: PdfTab;
  }) => (
    <div data-testid="pdf-canvas">
      Rendering {tab.title} page {tab.pageNumber}
      <button
        onClick={() =>
          onDocumentLoaded?.(
            tab.viewMode === "two-page" && tab.pageNumber >= 7 ? 8 : 200,
          )
        }
        type="button"
      >
        Report {tab.title} page count
      </button>
    </div>
  ),
}));

const openTabs: PdfTab[] = [
  {
    id: "core-rules",
    bookId: "core-rules",
    title: "Core Rules",
    pageNumber: 134,
    zoom: 1,
    viewMode: "single",
  },
  {
    id: "old-world",
    bookId: "old-world",
    title: "Old World Bestiary",
    pageNumber: 12,
    zoom: 1.2,
    viewMode: "single",
  },
];

function renderReader(overrides: Partial<Parameters<typeof PdfReaderPanel>[0]> = {}) {
  const props = {
    activeTabId: "core-rules",
    onCloseTab: vi.fn(),
    onSelectTab: vi.fn(),
    onSetPage: vi.fn(),
    openTabs,
    ...overrides,
  };

  renderApp(<PdfReaderPanel {...props} />);
  return props;
}

function renderControls(
  overrides: Partial<Parameters<typeof PdfReaderControls>[0]> = {},
) {
  const props = {
    activeTabId: "core-rules",
    onSetPage: vi.fn(),
    onSetViewMode: vi.fn(),
    onSetZoom: vi.fn(),
    openTabs,
    ...overrides,
  };

  renderApp(<PdfReaderControls {...props} />);
  return props;
}

describe("PdfReaderPanel", () => {
  it("renders source tabs without a duplicate page header", () => {
    renderReader();

    const coreTab = screen.getByRole("tab", { name: "Core Rules" });
    expect(coreTab).toHaveAttribute("aria-selected", "true");
    expect(coreTab).toHaveAttribute("aria-controls", "pdf-panel-core-rules");
    expect(
      screen.getByRole("tabpanel", { name: "Core Rules" }),
    ).toHaveAttribute("id", "pdf-panel-core-rules");
    expect(
      screen.getByRole("tab", { name: "Old World Bestiary" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("PDF tab actions")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Close Core Rules",
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("tablist", { name: "Open PDF sources" })).queryByRole(
        "button",
        { name: "Close Core Rules" },
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("pdf-canvas")).toHaveTextContent("Core Rules");
    expect(screen.queryByRole("tab", { name: /p\. 134/i })).not.toBeInTheDocument();
  });

  it("selects and closes PDF source tabs", async () => {
    const user = userEvent.setup();
    const props = renderReader();

    await user.click(screen.getByRole("tab", { name: /Old World Bestiary/i }));
    await user.click(screen.getByRole("button", { name: /Close Core Rules/i }));

    expect(props.onSelectTab).toHaveBeenCalledWith("old-world");
    expect(props.onCloseTab).toHaveBeenCalledWith("core-rules");
  });

  it("changes page from side controls", async () => {
    const user = userEvent.setup();
    const props = renderReader();

    await user.click(screen.getByRole("button", { name: "Previous page" }));
    await user.click(screen.getByRole("button", { name: "Next page" }));

    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 133);
    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 135);
  });

  it("does not render duplicate PDF controls inside the reader body", () => {
    renderReader();

    expect(screen.queryByLabelText("PDF controls")).not.toBeInTheDocument();
  });

  it("moves side controls by spreads in two-page view", async () => {
    const user = userEvent.setup();
    const props = renderReader({
      openTabs: [{ ...openTabs[0], pageNumber: 3, viewMode: "two-page" }],
    });

    await user.click(screen.getByRole("button", { name: "Previous page" }));
    await user.click(screen.getByRole("button", { name: "Next page" }));

    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 2);
    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 5);
  });

  it("uses the loaded page count to disable forward navigation at the end", async () => {
    const user = userEvent.setup();
    const props = renderReader({
      openTabs: [{ ...openTabs[0], pageNumber: 200 }],
    });

    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();

    await user.click(
      screen.getByRole("button", { name: "Report Core Rules page count" }),
    );

    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    expect(props.onSetPage).not.toHaveBeenCalled();
  });

  it("clamps an out-of-range active page after the page count loads", async () => {
    const user = userEvent.setup();
    const props = renderReader({
      openTabs: [{ ...openTabs[0], pageNumber: 999 }],
    });

    await user.click(
      screen.getByRole("button", { name: "Report Core Rules page count" }),
    );

    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 200);
    expect(screen.getByTestId("pdf-canvas")).toHaveTextContent(
      "Rendering Core Rules page 200",
    );
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("disables forward navigation on a final paired spread", async () => {
    const user = userEvent.setup();
    renderReader({
      openTabs: [{ ...openTabs[0], pageNumber: 7, viewMode: "two-page" }],
    });

    await user.click(
      screen.getByRole("button", { name: "Report Core Rules page count" }),
    );

    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("falls back to the first open tab if the active tab is missing", () => {
    renderReader({ activeTabId: "missing" });

    expect(
      screen.getByRole("tab", { name: "Core Rules" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("shows an empty state when no PDFs are open", () => {
    renderReader({ activeTabId: null, openTabs: [] });

    expect(
      screen.getByText("Open a source from Library or Search."),
    ).toBeInTheDocument();
  });
});

describe("PdfReaderControls", () => {
  it("changes page and zoom from the PDF header controls", async () => {
    const user = userEvent.setup();
    const props = renderControls();

    fireEvent.change(screen.getByRole("spinbutton", { name: "Page number" }), {
      target: { value: "42" },
    });
    await user.click(screen.getByRole("button", { name: "Zoom out" }));
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    await user.click(screen.getByRole("button", { name: "Fit width" }));

    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 42);
    expect(props.onSetZoom).toHaveBeenCalledWith("core-rules", 0.9);
    expect(props.onSetZoom).toHaveBeenCalledWith("core-rules", 1.1);
    expect(props.onSetZoom).toHaveBeenCalledWith("core-rules", 1);
  });

  it("does not render page arrows in the PDF header controls", () => {
    renderControls();

    const controls = screen.getByLabelText("PDF controls");

    expect(
      within(controls).queryByRole("button", { name: "Previous page" }),
    ).not.toBeInTheDocument();
    expect(
      within(controls).queryByRole("button", { name: "Next page" }),
    ).not.toBeInTheDocument();
  });

  it("shows single-page and two-page view controls", () => {
    renderControls();

    const controls = screen.getByLabelText("PDF controls");

    expect(
      within(controls).getByRole("button", { name: "Single-page view" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(controls).getByRole("button", { name: "Two-page view" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("selects two-page view mode", async () => {
    const user = userEvent.setup();
    const props = renderControls();

    await user.click(screen.getByRole("button", { name: "Two-page view" }));

    expect(props.onSetViewMode).toHaveBeenCalledWith("core-rules", "two-page");
  });

  it("selects single-page view mode", async () => {
    const user = userEvent.setup();
    const props = renderControls({
      openTabs: [{ ...openTabs[0], viewMode: "two-page" }],
    });

    await user.click(screen.getByRole("button", { name: "Single-page view" }));

    expect(props.onSetViewMode).toHaveBeenCalledWith("core-rules", "single");
  });

  it("renders nothing without an active PDF tab", () => {
    renderControls({ activeTabId: null, openTabs: [] });

    expect(screen.queryByLabelText("PDF controls")).not.toBeInTheDocument();
  });
});

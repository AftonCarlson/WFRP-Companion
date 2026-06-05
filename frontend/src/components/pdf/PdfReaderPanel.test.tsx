import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PdfTab } from "../../state/workspaceState";
import { renderApp } from "../../test/render";
import { PdfReaderPanel } from "./PdfReaderPanel";

vi.mock("./PdfCanvas", () => ({
  PdfCanvas: ({ tab }: { tab: PdfTab }) => (
    <div data-testid="pdf-canvas">Rendering {tab.title}</div>
  ),
}));

const openTabs: PdfTab[] = [
  {
    id: "core-rules",
    bookId: "core-rules",
    title: "Core Rules",
    pageNumber: 134,
    zoom: 1,
  },
  {
    id: "old-world",
    bookId: "old-world",
    title: "Old World Bestiary",
    pageNumber: 12,
    zoom: 1.2,
  },
];

function renderReader(overrides: Partial<Parameters<typeof PdfReaderPanel>[0]> = {}) {
  const props = {
    activeTabId: "core-rules",
    onCloseTab: vi.fn(),
    onSelectTab: vi.fn(),
    onSetPage: vi.fn(),
    onSetZoom: vi.fn(),
    openTabs,
    ...overrides,
  };

  renderApp(<PdfReaderPanel {...props} />);
  return props;
}

describe("PdfReaderPanel", () => {
  it("renders source tabs without a duplicate page header", () => {
    renderReader();

    expect(
      screen.getByRole("tab", { name: /Core Rules p\. 134/i }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tab", { name: /Core Rules p\. 134/i }),
    ).toHaveAttribute("aria-controls", "pdf-panel-core-rules");
    expect(
      screen.getByRole("tabpanel", { name: /Core Rules p\. 134/i }),
    ).toHaveAttribute("id", "pdf-panel-core-rules");
    expect(
      screen.getByRole("tab", { name: /Old World Bestiary p\. 12/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("pdf-canvas")).toHaveTextContent("Core Rules");
    expect(screen.queryByText("Core Rules - Page 134")).not.toBeInTheDocument();
  });

  it("selects and closes PDF source tabs", async () => {
    const user = userEvent.setup();
    const props = renderReader();

    await user.click(screen.getByRole("tab", { name: /Old World Bestiary/i }));
    await user.click(screen.getByRole("button", { name: /Close Core Rules/i }));

    expect(props.onSelectTab).toHaveBeenCalledWith("old-world");
    expect(props.onCloseTab).toHaveBeenCalledWith("core-rules");
  });

  it("changes page and zoom from the toolbar", async () => {
    const user = userEvent.setup();
    const props = renderReader();

    await user.click(screen.getByRole("button", { name: "Previous page" }));
    await user.click(screen.getByRole("button", { name: "Next page" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Page number" }), {
      target: { value: "42" },
    });
    await user.click(screen.getByRole("button", { name: "Zoom out" }));
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    await user.click(screen.getByRole("button", { name: "Fit width" }));

    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 133);
    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 135);
    expect(props.onSetPage).toHaveBeenCalledWith("core-rules", 42);
    expect(props.onSetZoom).toHaveBeenCalledWith("core-rules", 0.9);
    expect(props.onSetZoom).toHaveBeenCalledWith("core-rules", 1.1);
    expect(props.onSetZoom).toHaveBeenCalledWith("core-rules", 1);
  });

  it("falls back to the first open tab if the active tab is missing", () => {
    renderReader({ activeTabId: "missing" });

    expect(
      screen.getByRole("tab", { name: /Core Rules p\. 134/i }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("shows an empty state when no PDFs are open", () => {
    renderReader({ activeTabId: null, openTabs: [] });

    expect(
      screen.getByText("Open a source from Library or Search."),
    ).toBeInTheDocument();
  });
});

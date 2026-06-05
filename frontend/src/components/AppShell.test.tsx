import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import { renderApp } from "../test/render";
import { WORKSPACE_STORAGE_KEY } from "../state/workspaceStorage";
import { AppShell } from "./AppShell";

afterEach(() => {
  localStorage.clear();
});

function renderShell() {
  return renderApp(
    <AppShell
      agent={() => <div>Chat slot</div>}
      enabledBookCount={3}
      left={() => <div>Library slot</div>}
      reader={() => <div>Reader slot</div>}
    />,
  );
}

it("renders the three workspace panel slots", () => {
  renderShell();

  expect(screen.getByText("Library slot")).toBeInTheDocument();
  expect(screen.getByText("Reader slot")).toBeInTheDocument();
  expect(screen.getByText("Chat slot")).toBeInTheDocument();
  expect(screen.getByText("3 books enabled")).toBeInTheDocument();
});

it("collapses and restores a panel", async () => {
  const user = userEvent.setup();
  renderShell();

  await user.click(screen.getByRole("button", { name: "Collapse Agent Chat" }));

  expect(screen.queryByText("Chat slot")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Agent Chat" }));

  expect(screen.getByText("Chat slot")).toBeInTheDocument();
});

it("maximizes and restores a panel", async () => {
  const user = userEvent.setup();
  renderShell();

  await user.click(screen.getByRole("button", { name: "Maximize PDF Reader" }));

  expect(screen.getByText("Reader slot")).toBeInTheDocument();
  expect(screen.queryByText("Library slot")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Restore PDF Reader" }));

  expect(screen.getByText("Library slot")).toBeInTheDocument();
});

it("shows loading and error banners", () => {
  renderApp(
    <AppShell
      agent={() => <div />}
      enabledBookCount={0}
      error="Local API unavailable"
      left={() => <div />}
      loading
      reader={() => <div />}
    />,
  );

  expect(screen.getByText("Loading local library...")).toBeInTheDocument();
  expect(screen.getByText("Local API unavailable")).toBeInTheDocument();
});

it("opens the view menu and resets persisted layout", async () => {
  const user = userEvent.setup();
  localStorage.setItem(
    WORKSPACE_STORAGE_KEY,
    JSON.stringify({
      leftTab: "search",
      panels: {
        left: { size: 500, collapsed: true, maximized: false },
        reader: { size: 1, collapsed: false, maximized: false },
        agent: { size: 330, collapsed: false, maximized: false },
      },
      collapsedLibraryCategories: [],
      openPdfTabs: [],
      activePdfTabId: null,
    }),
  );
  renderShell();

  expect(screen.queryByText("Library slot")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "View" }));
  await user.click(screen.getByRole("button", { name: "Reset layout" }));

  expect(screen.getByText("Library slot")).toBeInTheDocument();
});

it("restores the library panel from top bar controls", async () => {
  const user = userEvent.setup();
  localStorage.setItem(
    WORKSPACE_STORAGE_KEY,
    JSON.stringify({
      leftTab: "search",
      panels: {
        left: { size: 500, collapsed: true, maximized: false },
        reader: { size: 1, collapsed: false, maximized: false },
        agent: { size: 330, collapsed: false, maximized: false },
      },
      collapsedLibraryCategories: [],
      openPdfTabs: [],
      activePdfTabId: null,
    }),
  );
  renderShell();

  expect(screen.queryByText("Library slot")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Library" }));

  expect(screen.getByText("Library slot")).toBeInTheDocument();
});

it("passes workspace state actions into panel slots", async () => {
  const user = userEvent.setup();

  renderApp(
    <AppShell
      agent={() => <div>Chat slot</div>}
      enabledBookCount={1}
      left={(context) => (
        <div>
          <span>Left tab {context.layout.leftTab}</span>
          <span>Collapsed categories {context.layout.collapsedLibraryCategories.join(",")}</span>
          <button
            onClick={() =>
              context.openPdfTab({
                bookId: "core-rules",
                title: "Core Rules",
                pageNumber: 4,
              })
            }
            type="button"
          >
            Open context PDF
          </button>
          <button onClick={() => context.setLeftTab("search")} type="button">
            Set search tab
          </button>
          <button
            onClick={() => context.toggleLibraryCategory("Rules / Core")}
            type="button"
          >
            Toggle category
          </button>
        </div>
      )}
      reader={(context) => {
        const activeTab = context.layout.openPdfTabs.find(
          (tab) => tab.id === context.layout.activePdfTabId,
        );
        return (
          <div>
            <span>Open tabs {context.layout.openPdfTabs.length}</span>
            <span>Active page {activeTab?.pageNumber ?? "none"}</span>
            <span>Active zoom {activeTab?.zoom ?? "none"}</span>
            <button onClick={() => context.selectPdfTab("core-rules")} type="button">
              Select context PDF
            </button>
            <button
              onClick={() => context.setPdfTabPage("core-rules", 12)}
              type="button"
            >
              Set context page
            </button>
            <button
              onClick={() => context.setPdfTabZoom("core-rules", 2)}
              type="button"
            >
              Set context zoom
            </button>
            <button onClick={() => context.closePdfTab("core-rules")} type="button">
              Close context PDF
            </button>
          </div>
        );
      }}
    />,
  );

  await user.click(screen.getByRole("button", { name: "Open context PDF" }));
  expect(screen.getByText("Open tabs 1")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Select context PDF" }));
  await user.click(screen.getByRole("button", { name: "Set context page" }));
  await user.click(screen.getByRole("button", { name: "Set context zoom" }));
  await user.click(screen.getByRole("button", { name: "Set search tab" }));
  await user.click(screen.getByRole("button", { name: "Toggle category" }));

  expect(screen.getByText("Active page 12")).toBeInTheDocument();
  expect(screen.getByText("Active zoom 2")).toBeInTheDocument();
  expect(screen.getByText("Left tab search")).toBeInTheDocument();
  expect(screen.getByText("Collapsed categories Rules / Core")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Close context PDF" }));

  expect(screen.getByText("Open tabs 0")).toBeInTheDocument();
});

it("resizes side panels by dragging dividers", () => {
  renderShell();

  fireEvent.pointerDown(
    screen.getByRole("separator", { name: "Resize Library and PDF Reader" }),
    { clientX: 300 },
  );
  fireEvent.pointerMove(window, { clientX: 340 });
  fireEvent.pointerUp(window);

  expect(
    screen.getByRole("main", { name: "WFRP Companion workspace" }),
  ).toContainElement(screen.getByText("Library slot"));
});

it("resizes the agent panel by dragging the right divider", () => {
  renderShell();

  fireEvent.pointerDown(
    screen.getByRole("separator", { name: "Resize PDF Reader and Agent Chat" }),
    { clientX: 700 },
  );
  fireEvent.pointerMove(window, { clientX: 680 });
  fireEvent.pointerUp(window);

  expect(
    screen.getByRole("main", { name: "WFRP Companion workspace" }),
  ).toContainElement(screen.getByText("Chat slot"));
});

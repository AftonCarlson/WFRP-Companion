import { screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { renderApp } from "../test/render";
import { WorkspacePanel } from "./WorkspacePanel";

it("renders panel header tools next to the title", () => {
  renderApp(
    <WorkspacePanel
      collapsed={false}
      headerTools={<button type="button">Header action</button>}
      maximized={false}
      onCollapse={vi.fn()}
      onMaximize={vi.fn()}
      title="GRIMOIRE"
    >
      Panel body
    </WorkspacePanel>,
  );

  const panel = screen.getByRole("region", { name: "GRIMOIRE" });
  expect(panel).toContainElement(screen.getByText("Header action"));
  expect(panel).toContainElement(screen.getByText("Panel body"));
});

it("renders nothing when already collapsed", () => {
  renderApp(
    <WorkspacePanel
      collapsed
      maximized={false}
      onCollapse={vi.fn()}
      onMaximize={vi.fn()}
      title="Library / Search"
    >
      Hidden body
    </WorkspacePanel>,
  );

  expect(screen.queryByText("Hidden body")).not.toBeInTheDocument();
});

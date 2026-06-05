import { screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { renderApp } from "../test/render";
import { WorkspacePanel } from "./WorkspacePanel";

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

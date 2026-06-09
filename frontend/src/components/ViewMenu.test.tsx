import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { renderApp } from "../test/render";
import { ViewMenu } from "./ViewMenu";

it("calls reset layout from the view menu", async () => {
  const user = userEvent.setup();
  const onResetLayout = vi.fn();

  renderApp(<ViewMenu onResetLayout={onResetLayout} />);

  expect(screen.getByLabelText("View options")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reset layout" }));

  expect(onResetLayout).toHaveBeenCalledOnce();
});

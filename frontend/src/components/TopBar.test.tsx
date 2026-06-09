import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { renderApp } from "../test/render";
import { TopBar } from "./TopBar";

it("shows enabled book count and focuses the library on demand", async () => {
  const user = userEvent.setup();
  const onFocusLibrary = vi.fn();

  renderApp(
    <TopBar
      enabledBookCount={5}
      onFocusLibrary={onFocusLibrary}
      viewMenuOpen
    />,
  );

  expect(screen.getByText("5 books enabled")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "View" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await user.click(screen.getByRole("button", { name: /library/i }));
  await user.click(screen.getByRole("button", { name: /5 books enabled/i }));

  expect(onFocusLibrary).toHaveBeenCalledTimes(2);
});

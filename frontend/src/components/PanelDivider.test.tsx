import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { renderApp } from "../test/render";
import { PanelDivider } from "./PanelDivider";

it("reports pointer movement deltas while dragging", () => {
  const onResize = vi.fn();
  renderApp(
    <PanelDivider
      label="Resize panels"
      onResize={onResize}
      valueMax={760}
      valueMin={220}
      valueNow={360}
    />,
  );

  fireEvent.pointerDown(screen.getByRole("separator", { name: "Resize panels" }), {
    clientX: 100,
  });
  fireEvent.pointerMove(window, { clientX: 125 });
  fireEvent.pointerMove(window, { clientX: 115 });
  fireEvent.pointerUp(window);
  fireEvent.pointerMove(window, { clientX: 150 });

  expect(onResize).toHaveBeenNthCalledWith(1, 25);
  expect(onResize).toHaveBeenNthCalledWith(2, -10);
  expect(onResize).toHaveBeenCalledTimes(2);
});

it("supports keyboard resizing for focusable separators", () => {
  const onResize = vi.fn();
  renderApp(
    <PanelDivider
      label="Resize panels"
      onResize={onResize}
      valueMax={760}
      valueMin={220}
      valueNow={360}
    />,
  );
  const separator = screen.getByRole("separator", { name: "Resize panels" });

  expect(separator).toHaveAttribute("aria-orientation", "vertical");
  expect(separator).toHaveAttribute("aria-valuemin", "220");
  expect(separator).toHaveAttribute("aria-valuemax", "760");
  expect(separator).toHaveAttribute("aria-valuenow", "360");

  fireEvent.keyDown(separator, { key: "ArrowRight" });
  fireEvent.keyDown(separator, { key: "ArrowLeft" });
  fireEvent.keyDown(separator, { key: "Home" });
  fireEvent.keyDown(separator, { key: "End" });
  fireEvent.keyDown(separator, { key: "Escape" });

  expect(onResize).toHaveBeenNthCalledWith(1, 24);
  expect(onResize).toHaveBeenNthCalledWith(2, -24);
  expect(onResize).toHaveBeenNthCalledWith(3, -140);
  expect(onResize).toHaveBeenNthCalledWith(4, 400);
  expect(onResize).toHaveBeenCalledTimes(4);
});

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";
import { AgentChatPanel } from "./AgentChatPanel";

describe("AgentChatPanel", () => {
  it("renders a scrollable transcript and controlled composer", async () => {
    const user = userEvent.setup();
    renderApp(<AgentChatPanel />);

    const transcript = screen.getByRole("log", { name: "Agent transcript" });
    const composer = screen.getByRole("textbox", { name: "Message" });

    expect(transcript).toBeInTheDocument();
    expect(
      screen.getByText(/AI Game Master aid is not connected yet/i),
    ).toBeInTheDocument();
    await user.type(composer, "Look up the grappling rule.");

    expect(composer).toHaveValue("Look up the grappling rule.");
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("opens the placeholder chat history menu", async () => {
    const user = userEvent.setup();
    renderApp(<AgentChatPanel />);

    await user.click(screen.getByRole("button", { name: "Open chat history" }));

    expect(screen.getByText("Chat history")).toBeInTheDocument();
    expect(
      screen.getByText(/chat persistence arrives in the agent phase/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Close chat history" }),
    ).toBeInTheDocument();
  });
});

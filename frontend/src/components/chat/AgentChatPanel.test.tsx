import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";
import { AgentChatHeaderControls, AgentChatPanel } from "./AgentChatPanel";

function AgentChatHarness() {
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <>
      <AgentChatHeaderControls
        historyOpen={historyOpen}
        setHistoryOpen={setHistoryOpen}
      />
      <AgentChatPanel historyOpen={historyOpen} />
    </>
  );
}

describe("AgentChatPanel", () => {
  it("renders a scrollable transcript and controlled composer", async () => {
    const user = userEvent.setup();
    renderApp(<AgentChatHarness />);

    const transcript = screen.getByRole("log", { name: "Agent transcript" });
    const composer = screen.getByRole("textbox", { name: "Message" });

    expect(transcript).toBeInTheDocument();
    expect(screen.queryByText("Game Master Aid")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Familiar is not connected yet/i),
    ).toBeInTheDocument();
    await user.type(composer, "Look up the grappling rule.");

    expect(composer).toHaveValue("Look up the grappling rule.");
    expect(
      composer.closest(".agent-chat__composer-field"),
    ).toContainElement(screen.getByRole("button", { name: "Send message" }));
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("opens the placeholder chat history menu", async () => {
    const user = userEvent.setup();
    renderApp(<AgentChatHarness />);

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

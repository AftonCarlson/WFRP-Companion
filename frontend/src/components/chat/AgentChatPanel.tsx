import { Menu, Send } from "lucide-react";
import { useState, type Dispatch, type SetStateAction } from "react";

import "./AgentChatPanel.css";

export type AgentChatPanelProps = {
  historyOpen?: boolean;
};

export type AgentChatHeaderControlsProps = {
  historyOpen: boolean;
  setHistoryOpen: Dispatch<SetStateAction<boolean>>;
};

export function AgentChatHeaderControls({
  historyOpen,
  setHistoryOpen,
}: AgentChatHeaderControlsProps) {
  return (
    <button
      aria-expanded={historyOpen}
      aria-label={historyOpen ? "Close chat history" : "Open chat history"}
      className="agent-chat__history-toggle"
      onClick={() => setHistoryOpen((open) => !open)}
      type="button"
    >
      <Menu aria-hidden="true" size={17} />
    </button>
  );
}

export function AgentChatPanel({ historyOpen = false }: AgentChatPanelProps) {
  const [message, setMessage] = useState("");

  return (
    <div className="agent-chat">
      {historyOpen ? (
        <div className="agent-chat__history">
          <strong>Chat history</strong>
          <p>Chat persistence arrives in the agent phase.</p>
        </div>
      ) : null}
      <div className="agent-chat__transcript" role="log" aria-label="Agent transcript">
        <article>
          <strong>Agent offline</strong>
          <p>
            Familiar is not connected yet. This panel is ready for the chat
            API, retrieval context, and future voice features.
          </p>
        </article>
      </div>
      <form className="agent-chat__composer" aria-label="Agent message composer">
        <div className="agent-chat__composer-field">
          <textarea
            aria-label="Message"
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Ask about a rule, source page, NPC, or scene..."
            rows={4}
            value={message}
          />
          <button aria-label="Send message" disabled type="submit">
            <Send aria-hidden="true" size={16} />
          </button>
        </div>
      </form>
    </div>
  );
}

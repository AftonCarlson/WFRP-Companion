import { Menu, Send } from "lucide-react";
import { useState } from "react";

import "./AgentChatPanel.css";

export function AgentChatPanel() {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [message, setMessage] = useState("");

  return (
    <div className="agent-chat">
      <div className="agent-chat__header">
        <button
          aria-expanded={historyOpen}
          aria-label={historyOpen ? "Close chat history" : "Open chat history"}
          onClick={() => setHistoryOpen((open) => !open)}
          type="button"
        >
          <Menu aria-hidden="true" size={17} />
        </button>
        <span>Game Master Aid</span>
      </div>
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
            AI Game Master aid is not connected yet. This panel is ready for
            the chat API, retrieval context, and future voice features.
          </p>
        </article>
      </div>
      <form className="agent-chat__composer" aria-label="Agent message composer">
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
      </form>
    </div>
  );
}

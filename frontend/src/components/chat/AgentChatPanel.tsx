import { Menu, Send } from "lucide-react";
import {
  useState,
  type Dispatch,
  type FormEvent,
  type KeyboardEvent,
  type SetStateAction,
} from "react";

import { apiClient, type ApiClient } from "../../lib/apiClient";
import { errorMessage } from "../../lib/apiError";
import type {
  ChatCitationResponse,
  ChatMessageResponse,
  ChatStreamEvent,
  ModelRunResponse,
} from "../../types/api";
import "./AgentChatPanel.css";

export type AgentChatPanelProps = {
  client?: ApiClient;
  historyOpen?: boolean;
  onOpenCitation?: (citation: ChatCitationResponse) => void;
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

type TranscriptTurn = {
  id: string;
  userMessage: ChatMessageResponse;
  assistantContent: string;
  citations: ChatCitationResponse[];
  errorMessage: string | null;
  modelRun: ModelRunResponse | null;
};

export function AgentChatPanel({
  client = apiClient,
  historyOpen = false,
  onOpenCitation,
}: AgentChatPanelProps) {
  const [message, setMessage] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [sending, setSending] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);

  async function ensureThread(): Promise<string> {
    if (threadId) {
      return threadId;
    }
    const thread = await client.createChatThread({});
    setThreadId(thread.id);
    return thread.id;
  }

  async function sendCurrentMessage() {
    const content = message.trim();
    if (!content || sending) {
      return;
    }
    setSending(true);
    setPanelError(null);
    setMessage("");
    try {
      const activeThreadId = await ensureThread();
      const idempotencyKey =
        globalThis.crypto?.randomUUID?.() ?? `send-${Date.now()}`;
      await client.streamChatMessage(activeThreadId, {
        content,
        idempotency_key: idempotencyKey,
        onEvent: handleStreamEvent,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      setPanelError(errorMessage(error));
    } finally {
      setSending(false);
    }
  }

  async function retryTurn(turnId: string, modelRunId: string) {
    setPanelError(null);
    try {
      const idempotencyKey =
        globalThis.crypto?.randomUUID?.() ?? `retry-${Date.now()}`;
      const result = await client.retryModelRun(modelRunId, idempotencyKey);
      setTurns((currentTurns) =>
        currentTurns.map((turn) =>
          turn.id === turnId
            ? {
                ...turn,
                id: result.model_run.id,
                assistantContent: result.assistant_message?.content ?? "",
                citations: result.citations,
                errorMessage:
                  result.model_run.error_message ??
                  (result.model_run.status === "failed"
                    ? "Familiar could not complete the response."
                    : null),
                modelRun: result.model_run,
              }
            : turn,
        ),
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      setPanelError(errorMessage(error));
    }
  }

  function handleStreamEvent(event: ChatStreamEvent) {
    if (event.type === "accepted" && event.user_message) {
      const userMessage = event.user_message;
      setTurns((currentTurns) => [
        ...currentTurns,
        {
          id: event.model_run?.id ?? userMessage.id,
          userMessage,
          assistantContent: "",
          citations: event.citations ?? [],
          errorMessage: event.error_message ?? null,
          modelRun: event.model_run ?? null,
        },
      ]);
      return;
    }
    setTurns((currentTurns) => {
      if (!currentTurns.length) {
        return currentTurns;
      }
      const nextTurns = [...currentTurns];
      const lastTurn = nextTurns[nextTurns.length - 1];
      if (event.type === "delta" && event.text_delta) {
        nextTurns[nextTurns.length - 1] = {
          ...lastTurn,
          assistantContent: lastTurn.assistantContent + event.text_delta,
        };
      } else if (event.type === "completed") {
        nextTurns[nextTurns.length - 1] = {
          ...lastTurn,
          assistantContent:
            event.assistant_message?.content || lastTurn.assistantContent,
          citations: event.citations ?? lastTurn.citations,
          modelRun: event.model_run ?? lastTurn.modelRun,
        };
      } else if (event.type === "failed") {
        nextTurns[nextTurns.length - 1] = {
          ...lastTurn,
          citations: event.citations ?? lastTurn.citations,
          errorMessage:
            event.error_message ??
            event.model_run?.error_message ??
            "Familiar could not complete the response.",
          modelRun: event.model_run ?? lastTurn.modelRun,
        };
      } else if (event.type === "retrieval") {
        nextTurns[nextTurns.length - 1] = {
          ...lastTurn,
          citations: event.citations ?? lastTurn.citations,
        };
      }
      return nextTurns;
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendCurrentMessage();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendCurrentMessage();
    }
  }

  const canSend = message.trim().length > 0 && !sending;

  return (
    <div className="agent-chat">
      {historyOpen ? (
        <div className="agent-chat__history">
          <strong>Chat history</strong>
          <p>Chat persistence arrives in the agent phase.</p>
        </div>
      ) : null}
      <div className="agent-chat__transcript" role="log" aria-label="Agent transcript">
        {turns.length === 0 ? (
          <article>
            <strong>Familiar ready</strong>
            <p>Ask about a rule, source page, NPC, or scene.</p>
          </article>
        ) : null}
        {turns.map((turn) => (
          <article className="agent-chat__turn" key={turn.id}>
            <strong>You</strong>
            <p>{turn.userMessage.content}</p>
            {turn.assistantContent ? (
              <>
                <strong>Familiar</strong>
                <p>{turn.assistantContent}</p>
              </>
            ) : null}
            {turn.errorMessage ? (
              <div className="agent-chat__error">
                <p>{turn.errorMessage}</p>
                <button
                  type="button"
                  disabled={!turn.modelRun?.retryable}
                  onClick={() => {
                    if (turn.modelRun?.id) {
                      void retryTurn(turn.id, turn.modelRun.id);
                    }
                  }}
                >
                  Retry message
                </button>
              </div>
            ) : null}
            {turn.citations.length ? (
              <div className="agent-chat__citations" aria-label="Citations">
                {turn.citations.map((citation) => (
                  <button
                    key={`${citation.book_id}:${citation.page_number}:${citation.rank}`}
                    onClick={() => onOpenCitation?.(citation)}
                    type="button"
                  >
                    Open {citation.title} page {citation.page_number}
                  </button>
                ))}
              </div>
            ) : null}
          </article>
        ))}
        {panelError ? (
          <article className="agent-chat__error">
            <p>{panelError}</p>
          </article>
        ) : null}
      </div>
      <form
        className="agent-chat__composer"
        aria-label="Agent message composer"
        onSubmit={handleSubmit}
      >
        <div className="agent-chat__composer-field">
          <textarea
            aria-label="Message"
            disabled={sending}
            onKeyDown={handleKeyDown}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Ask about a rule, source page, NPC, or scene..."
            rows={4}
            value={message}
          />
          <button aria-label="Send message" disabled={!canSend} type="submit">
            <Send aria-hidden="true" size={16} />
          </button>
        </div>
      </form>
    </div>
  );
}

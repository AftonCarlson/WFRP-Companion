import { Menu, Send } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
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
  ChatThreadDetailResponse,
  ChatThreadResponse,
  ChatTurnResponse,
  ModelRunResponse,
} from "../../types/api";
import { MarkdownText } from "./MarkdownText";
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
  const [historyThreads, setHistoryThreads] = useState<ChatThreadResponse[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);
  const sendingRef = useRef(false);
  const activeStreamThreadIdRef = useRef<string | null>(null);

  const loadHistoryThreads = useCallback(
    async (signal?: AbortSignal) => {
      setHistoryLoading(true);
      setHistoryError(null);
      try {
        const response = await client.listChatThreads({ signal });
        setHistoryThreads(response.threads);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setHistoryError(errorMessage(error));
      } finally {
        setHistoryLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    if (!historyOpen) {
      return;
    }
    const controller = new AbortController();
    void loadHistoryThreads(controller.signal);
    return () => controller.abort();
  }, [historyOpen, loadHistoryThreads]);

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
    if (!content || sendingRef.current) {
      return;
    }
    sendingRef.current = true;
    setSending(true);
    setPanelError(null);
    setMessage("");
    try {
      const activeThreadId = await ensureThread();
      activeStreamThreadIdRef.current = activeThreadId;
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
      activeStreamThreadIdRef.current = null;
      sendingRef.current = false;
      setSending(false);
      if (historyOpen) {
        void loadHistoryThreads();
      }
    }
  }

  async function selectHistoryThread(selectedThreadId: string) {
    if (sendingRef.current) {
      return;
    }
    setPanelError(null);
    setHistoryError(null);
    try {
      const detail = await client.getChatThread(selectedThreadId);
      if (sendingRef.current) {
        return;
      }
      setThreadId(detail.thread.id);
      setTurns(threadDetailToTranscriptTurns(detail));
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      setHistoryError(errorMessage(error));
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
    const activeStreamThreadId = activeStreamThreadIdRef.current;
    const eventThreadId =
      event.thread?.id ??
      event.model_run?.thread_id ??
      event.user_message?.thread_id ??
      event.assistant_message?.thread_id ??
      null;
    if (
      activeStreamThreadId &&
      eventThreadId &&
      eventThreadId !== activeStreamThreadId
    ) {
      return;
    }
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
      const targetIndex = targetTurnIndex(nextTurns, event);
      if (targetIndex < 0) {
        return currentTurns;
      }
      const targetTurn = nextTurns[targetIndex];
      if (event.type === "delta" && event.text_delta) {
        nextTurns[targetIndex] = {
          ...targetTurn,
          assistantContent: targetTurn.assistantContent + event.text_delta,
        };
      } else if (event.type === "completed") {
        nextTurns[targetIndex] = {
          ...targetTurn,
          assistantContent:
            event.assistant_message?.content || targetTurn.assistantContent,
          citations: event.citations ?? targetTurn.citations,
          modelRun: event.model_run ?? targetTurn.modelRun,
        };
      } else if (event.type === "failed") {
        nextTurns[targetIndex] = {
          ...targetTurn,
          citations: event.citations ?? targetTurn.citations,
          errorMessage:
            event.error_message ??
            event.model_run?.error_message ??
            "Familiar could not complete the response.",
          modelRun: event.model_run ?? targetTurn.modelRun,
        };
      } else if (event.type === "retrieval") {
        nextTurns[targetIndex] = {
          ...targetTurn,
          citations: event.citations ?? targetTurn.citations,
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
          {historyLoading ? <p>Loading...</p> : null}
          {historyError ? <p>{historyError}</p> : null}
          {!historyLoading && !historyError && historyThreads.length === 0 ? (
            <p>No saved chats yet.</p>
          ) : null}
          {historyThreads.length ? (
            <div className="agent-chat__history-list">
              {historyThreads.map((thread) => (
                <button
                  className="agent-chat__history-item"
                  disabled={sending}
                  key={thread.id}
                  onClick={() => void selectHistoryThread(thread.id)}
                  type="button"
                >
                  <strong>{thread.title || "Familiar Chat"}</strong>
                  <span>{formatThreadUpdatedAt(thread.updated_at)}</span>
                </button>
              ))}
            </div>
          ) : null}
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
                <MarkdownText content={turn.assistantContent} />
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
                    key={`${citation.book_id}:${citation.pdf_page_number}:${citation.rank}`}
                    onClick={() => onOpenCitation?.(citation)}
                    type="button"
                  >
                    {citationButtonLabel(citation)}
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

function citationButtonLabel(citation: ChatCitationResponse) {
  if (citation.page_range_label) {
    if (citation.page_range_label.includes("-")) {
      return `Open ${citation.title} printed pages ${citation.page_range_label}`;
    }
    return `Open ${citation.title} printed page ${citation.page_range_label}`;
  }
  if (
    citation.page_label &&
    citation.page_label !== String(citation.pdf_page_number)
  ) {
    return `Open ${citation.title} printed page ${citation.page_label}`;
  }
  return `Open ${citation.title} page ${citation.page_number}`;
}

function threadDetailToTranscriptTurns(
  detail: ChatThreadDetailResponse,
): TranscriptTurn[] {
  return detail.turns.map(turnResponseToTranscriptTurn);
}

function turnResponseToTranscriptTurn(turn: ChatTurnResponse): TranscriptTurn {
  return {
    id: turn.model_run.id,
    userMessage: turn.user_message,
    assistantContent: turn.assistant_message?.content ?? "",
    citations: turn.citations,
    errorMessage:
      turn.model_run.error_message ??
      (turn.model_run.status === "failed"
        ? "Familiar could not complete the response."
        : null),
    modelRun: turn.model_run,
  };
}

function targetTurnIndex(
  turns: TranscriptTurn[],
  event: ChatStreamEvent,
): number {
  if (event.model_run?.id) {
    const index = turns.findIndex(
      (turn) => turn.modelRun?.id === event.model_run?.id,
    );
    if (index >= 0) {
      return index;
    }
    return -1;
  }
  return turns.length - 1;
}

function formatThreadUpdatedAt(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(timestamp);
}

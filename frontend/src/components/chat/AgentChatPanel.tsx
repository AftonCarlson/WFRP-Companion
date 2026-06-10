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
  ReaderContextRequest,
} from "../../types/api";
import { MarkdownText } from "./MarkdownText";
import "./AgentChatPanel.css";

const MAX_RESEARCH_TRACE_ITEMS = 12;

export type AgentChatPanelProps = {
  client?: ApiClient;
  historyOpen?: boolean;
  onOpenCitation?: (citation: ChatCitationResponse) => void;
  readerContext?: ReaderContextRequest | null;
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
  researchTrace: string[];
};

export function AgentChatPanel({
  client = apiClient,
  historyOpen = false,
  onOpenCitation,
  readerContext = null,
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
        reader_context: readerContext,
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
          researchTrace: [],
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
      const traceLabel = researchTraceLabel(event);
      let updatedTurn = targetTurn;
      if (event.type === "delta" && event.text_delta) {
        updatedTurn = {
          ...targetTurn,
          assistantContent: targetTurn.assistantContent + event.text_delta,
        };
      } else if (event.type === "completed") {
        updatedTurn = {
          ...targetTurn,
          assistantContent:
            event.assistant_message?.content || targetTurn.assistantContent,
          citations: event.citations ?? targetTurn.citations,
          modelRun: event.model_run ?? targetTurn.modelRun,
        };
      } else if (event.type === "failed") {
        updatedTurn = {
          ...targetTurn,
          citations: event.citations ?? targetTurn.citations,
          errorMessage:
            event.error_message ??
            event.model_run?.error_message ??
            "Familiar could not complete the response.",
          modelRun: event.model_run ?? targetTurn.modelRun,
        };
      } else if (event.type === "retrieval") {
        updatedTurn = {
          ...targetTurn,
          citations: event.citations ?? targetTurn.citations,
        };
      }
      if (traceLabel) {
        updatedTurn = {
          ...updatedTurn,
          researchTrace: appendResearchTrace(
            updatedTurn.researchTrace,
            traceLabel,
          ),
        };
      }
      nextTurns[targetIndex] = updatedTurn;
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
            {turn.researchTrace.length ? (
              <details className="agent-chat__trace">
                <summary>{lastTraceLabel(turn.researchTrace)}</summary>
                <ol>
                  {turn.researchTrace.map((item, index) => (
                    <li key={`${item}:${index}`}>{item}</li>
                  ))}
                </ol>
              </details>
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
    researchTrace: (turn.research_events ?? []).map((event) => event.label),
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

function appendResearchTrace(currentTrace: string[], item: string): string[] {
  if (currentTrace[currentTrace.length - 1] === item) {
    return currentTrace;
  }
  return [...currentTrace, item].slice(-MAX_RESEARCH_TRACE_ITEMS);
}

function lastTraceLabel(trace: string[]): string {
  return trace[trace.length - 1] ?? "Research trace";
}

function researchTraceLabel(event: ChatStreamEvent): string | null {
  const metadata = event.metadata ?? {};
  if (event.type === "turn_decision") {
    const answerMode = stringValue(metadata.answer_mode);
    if (answerMode !== "research") {
      return null;
    }
    const turnKind = stringValue(metadata.turn_kind);
    return turnKind
      ? `${shortLabel(turnKind.replace(/_/g, " "))}; research`
      : "Research turn";
  }
  if (event.type === "research_started") {
    return "Research started";
  }
  if (event.type === "research_plan") {
    return "Research plan accepted";
  }
  if (event.type === "tool_call") {
    return toolCallTraceLabel(metadata);
  }
  if (event.type === "retrieval") {
    const candidateCount = numberValue(metadata.candidate_hit_count);
    const acceptedCount = event.citations?.length ?? 0;
    return candidateCount === null
      ? `Retrieved ${acceptedCount} accepted citation(s)`
      : `Retrieved ${candidateCount} candidate(s); ${acceptedCount} accepted citation(s)`;
  }
  if (event.type === "tool_result") {
    const hitCount = numberValue(metadata.hit_count);
    const diagnostics = recordValue(metadata.diagnostics);
    const vectorStatus = stringValue(diagnostics?.vector_status);
    const base =
      hitCount === null
        ? "Tool returned results"
        : `Tool returned ${hitCount} candidate(s)`;
    return vectorStatus ? `${base}; vector ${vectorStatus}` : base;
  }
  if (event.type === "evidence_validation") {
    const status = stringValue(metadata.evidence_status) ?? "unknown";
    const accepted = numberValue(metadata.accepted_hit_count);
    const partial = numberValue(metadata.partial_hit_count);
    const rejected = numberValue(metadata.rejected_hit_count);
    const reasonCounts = reasonCountsLabel(recordValue(metadata.reason_counts));
    return accepted === null
      ? `Evidence ${status}`
      : `Evidence ${status}; ${[
          `${accepted} accepted`,
          partial === null ? null : `${partial} partial`,
          rejected === null ? null : `${rejected} rejected`,
        ]
          .filter(Boolean)
          .join(", ")}${reasonCounts ? ` (${reasonCounts})` : ""}`;
  }
  if (event.type === "finalizing") {
    return "Answering from evidence";
  }
  if (event.type === "failed") {
    return "Research failed";
  }
  return null;
}

function toolCallTraceLabel(metadata: Record<string, unknown>): string {
  const toolName = stringValue(metadata.tool_name);
  const argumentsRecord = recordValue(metadata.arguments);
  if (toolName === "open_page") {
    const printedPage = stringValue(argumentsRecord?.printed_page_label);
    const pdfPage = numberValue(argumentsRecord?.pdf_page_number);
    const page = printedPage ?? (pdfPage === null ? null : String(pdfPage));
    return page ? `Opening page ${shortLabel(page)}` : "Opening source page";
  }
  if (toolName === "search_library") {
    return "Running hybrid search";
  }
  if (toolName === "lookup_source_object") {
    return "Inspecting source object";
  }
  return toolName ? `Running ${toolName}` : "Running research tool";
}

function reasonCountsLabel(reasonCounts: Record<string, unknown> | null): string {
  if (!reasonCounts) {
    return "";
  }
  return Object.entries(reasonCounts)
    .filter((entry): entry is [string, number] => typeof entry[1] === "number")
    .sort(([left], [right]) => left.localeCompare(right))
    .slice(0, 4)
    .map(([reason, count]) => `${shortLabel(reason)} ${count}`)
    .join(", ");
}

function recordValue(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function shortLabel(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > 60 ? `${normalized.slice(0, 57)}...` : normalized;
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

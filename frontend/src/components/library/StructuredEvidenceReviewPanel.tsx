import { useEffect, useMemo, useState } from "react";

import type { ApiClient } from "../../lib/apiClient";
import { apiClient } from "../../lib/apiClient";
import { errorMessage } from "../../lib/apiError";
import type { PdfViewMode } from "../../state/workspaceState";
import type {
  StructuredCandidateDetailResponse,
  StructuredCandidateSummaryResponse,
  StructuredReviewSummaryResponse,
} from "../../types/api";
import "./StructuredEvidenceReviewPanel.css";

export type StructuredEvidenceReviewPanelProps = {
  client?: ApiClient;
  onOpenPdfPage: (input: {
    bookId: string;
    title: string;
    pageNumber: number;
    viewMode?: PdfViewMode;
  }) => void;
};

export function StructuredEvidenceReviewPanel({
  client = apiClient,
  onOpenPdfPage,
}: StructuredEvidenceReviewPanelProps) {
  const [summary, setSummary] = useState<StructuredReviewSummaryResponse | null>(
    null,
  );
  const [candidates, setCandidates] = useState<StructuredCandidateSummaryResponse[]>(
    [],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<StructuredCandidateDetailResponse | null>(
    null,
  );
  const [payloadText, setPayloadText] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [savingAction, setSavingAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refreshQueue(nextSelectedId?: string | null) {
    setLoading(true);
    setError(null);
    try {
      const [summaryResponse, candidateResponse] = await Promise.all([
        client.getStructuredReviewSummary(),
        client.listStructuredCandidates({ limit: 50 }),
      ]);
      setSummary(summaryResponse);
      setCandidates(candidateResponse.candidates);
      const nextId = nextSelectedId ?? candidateResponse.candidates[0]?.id ?? null;
      setSelectedId(nextId);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setPayloadText("");
      return;
    }
    const candidateId = selectedId;
    let cancelled = false;
    async function loadDetail() {
      setDetailLoading(true);
      setError(null);
      try {
        const response = await client.getStructuredCandidate(candidateId);
        if (!cancelled) {
          setDetail(response);
          setPayloadText(JSON.stringify(response.payload_json, null, 2));
        }
      } catch (caught) {
        if (!cancelled) {
          setError(errorMessage(caught));
        }
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    }
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [client, selectedId]);

  const selectedCandidate = useMemo(
    () => candidates.find((candidate) => candidate.id === selectedId) ?? null,
    [candidates, selectedId],
  );

  async function runReviewAction(action: "approve" | "correct" | "reject") {
    if (!detail) {
      return;
    }
    setSavingAction(action);
    setError(null);
    try {
      if (action === "approve") {
        await client.approveStructuredCandidate(detail.id, { reviewer: "local" });
      } else if (action === "reject") {
        await client.rejectStructuredCandidate(detail.id, { reviewer: "local" });
      } else {
        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(payloadText) as Record<string, unknown>;
        } catch {
          setError("Payload JSON is invalid.");
          return;
        }
        await client.correctStructuredCandidate(detail.id, {
          payload_json: payload,
          reviewer: "local",
        });
      }
      await refreshQueue(detail.id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSavingAction(null);
    }
  }

  function openSelectedPage() {
    if (!detail) {
      return;
    }
    onOpenPdfPage({
      bookId: detail.book_id,
      title: detail.book_title,
      pageNumber: detail.page_start,
      viewMode: "single",
    });
  }

  return (
    <div className="structured-review">
      <div
        aria-label="Structured evidence status"
        className="structured-review__summary"
      >
        {summary ? (
          <>
            <span>Structured: {summary.candidates_total} candidates</span>
            <span>{summary.candidates_needs_review} needs review</span>
            <span>{summary.candidates_blocked} blocked</span>
            <span>{summary.validated_active} validated</span>
          </>
        ) : (
          <span>Structured: loading</span>
        )}
      </div>
      {error ? <div className="inline-error">{error}</div> : null}
      <div className="structured-review__body">
        <div className="structured-review__queue" aria-label="Review queue">
          {loading ? <div className="muted">Loading...</div> : null}
          {!loading && candidates.length === 0 ? (
            <div className="muted">No candidates.</div>
          ) : null}
          {candidates.map((candidate) => (
            <button
              aria-pressed={candidate.id === selectedId}
              className="structured-review__candidate"
              key={candidate.id}
              onClick={() => setSelectedId(candidate.id)}
              type="button"
            >
              <span>{candidate.title ?? candidate.canonical_name ?? candidate.id}</span>
              <small>
                {candidate.book_title} · p. {candidate.page_start} ·{" "}
                {Math.round(candidate.confidence * 100)}%
              </small>
              <span className="structured-review__flags">
                {candidate.suspicious_flags.length
                  ? candidate.suspicious_flags.join(", ")
                  : candidate.status}
              </span>
            </button>
          ))}
        </div>
        <div className="structured-review__detail">
          {detailLoading ? <div className="muted">Loading detail...</div> : null}
          {!detailLoading && selectedCandidate && detail ? (
            <>
              <div className="structured-review__detail-header">
                <h3>{detail.title ?? detail.canonical_name ?? detail.id}</h3>
                <button onClick={openSelectedPage} type="button">
                  Open page {detail.page_start}
                </button>
              </div>
              <dl className="structured-review__facts">
                <div>
                  <dt>Type</dt>
                  <dd>{detail.object_shape.replace("_", " ")}</dd>
                </div>
                <div>
                  <dt>Flags</dt>
                  <dd>
                    {detail.suspicious_flags.length
                      ? detail.suspicious_flags.join(", ")
                      : detail.status}
                  </dd>
                </div>
              </dl>
              <label className="structured-review__editor">
                <span>Structured payload JSON</span>
                <textarea
                  aria-label="Structured payload JSON"
                  onChange={(event) => setPayloadText(event.currentTarget.value)}
                  spellCheck={false}
                  value={payloadText}
                />
              </label>
              <details className="structured-review__observations">
                <summary>Observations</summary>
                {detail.observations.map((observation) => (
                  <div key={observation.id}>
                    <span>{observation.reader_name}</span>
                    <small>
                      {observation.observation_type} ·{" "}
                      {Math.round(observation.confidence * 100)}%
                    </small>
                  </div>
                ))}
              </details>
              <div className="structured-review__actions">
                <button
                  disabled={savingAction !== null}
                  onClick={() => void runReviewAction("approve")}
                  type="button"
                >
                  Approve
                </button>
                <button
                  disabled={savingAction !== null}
                  onClick={() => void runReviewAction("correct")}
                  type="button"
                >
                  Correct
                </button>
                <button
                  disabled={savingAction !== null}
                  onClick={() => void runReviewAction("reject")}
                  type="button"
                >
                  Reject
                </button>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

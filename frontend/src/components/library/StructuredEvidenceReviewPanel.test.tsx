import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { ApiClient } from "../../lib/apiClient";
import { renderApp } from "../../test/render";
import { StructuredEvidenceReviewPanel } from "./StructuredEvidenceReviewPanel";

const candidate = {
  id: "candidate-1",
  book_id: "core-rules",
  book_title: "Core Rules",
  object_shape: "structured_table",
  content_kind: "equipment_table",
  entity_kind: "none",
  canonical_name: null,
  title: "Table 5-6: Advanced Armour",
  table_number: "Table 5-6",
  table_number_normalized: "5-6",
  page_start: 112,
  page_end: 112,
  printed_page_start: "112",
  printed_page_end: "112",
  confidence: 0.76,
  suspicious_flags: ["referenced_table_missing"],
  status: "needs_review",
  updated_at: "2026-06-10T00:00:00Z",
};

const detail = {
  ...candidate,
  primary_page_id: "core-rules:112",
  primary_source_object_id: "table",
  heading_path: ["Chapter V", "Armour"],
  payload_json: {
    schema_version: 1,
    object_shape: "structured_table",
    identity: {
      title_normalized: "table 5 6 advanced armour",
      aliases: ["table 5-6"],
    },
  },
  text_snapshot_sha256: "text-snapshot",
  structured_extractor_version: "test-v1",
  observations: [
    {
      id: "observation-1",
      reader_name: "source_object_heuristic",
      reader_version: "reader-v1",
      observation_type: "table_region",
      object_shape: "structured_table",
      content_kind: "equipment_table",
      entity_kind: "none",
      title: "Table 5-6: Advanced Armour",
      table_number: "5-6",
      canonical_name: null,
      page_number: 112,
      confidence: 0.76,
      text_hash: "hash",
    },
  ],
};

function client(overrides: Partial<ApiClient> = {}) {
  return {
    getStructuredReviewSummary: vi.fn().mockResolvedValue({
      candidates_total: 3,
      candidates_needs_review: 1,
      validated_active: 2,
      validated_stale: 0,
      validated_retired: 1,
    }),
    listStructuredCandidates: vi.fn().mockResolvedValue({
      candidates: [candidate],
    }),
    getStructuredCandidate: vi.fn().mockResolvedValue(detail),
    approveStructuredCandidate: vi.fn().mockResolvedValue({
      action: "approve",
      candidate_id: "candidate-1",
      validated_object_id: "validated-1",
      review_id: "review-1",
      source_snapshot_sha256: "snapshot",
    }),
    correctStructuredCandidate: vi.fn().mockResolvedValue({
      action: "correct",
      candidate_id: "candidate-1",
      validated_object_id: "validated-1",
      review_id: "review-1",
      source_snapshot_sha256: "snapshot",
    }),
    rejectStructuredCandidate: vi.fn().mockResolvedValue({
      action: "reject",
      candidate_id: "candidate-1",
      validated_object_id: null,
      review_id: "review-1",
      source_snapshot_sha256: null,
    }),
    getHealth: vi.fn(),
    listBooks: vi.fn(),
    getRetrievalStatus: vi.fn(),
    listSourceSets: vi.fn(),
    listSourceSetBooks: vi.fn(),
    setSourceSetBook: vi.fn(),
    searchExact: vi.fn(),
    getPageText: vi.fn(),
    createChatThread: vi.fn(),
    listChatThreads: vi.fn(),
    getChatThread: vi.fn(),
    sendChatMessage: vi.fn(),
    retryModelRun: vi.fn(),
    streamChatMessage: vi.fn(),
    ...overrides,
  } as ApiClient;
}

it("renders structured review status, flags, and candidate detail", async () => {
  renderApp(
    <StructuredEvidenceReviewPanel
      client={client()}
      onOpenPdfPage={vi.fn()}
    />,
  );

  expect(await screen.findByText("Structured: 3 candidates")).toBeInTheDocument();
  expect(screen.getByText("1 needs review")).toBeInTheDocument();
  expect(screen.getByText("2 validated")).toBeInTheDocument();
  await screen.findByText("source_object_heuristic");
  expect(screen.getAllByText("Table 5-6: Advanced Armour")).toHaveLength(2);
  expect(screen.getAllByText("referenced_table_missing")).toHaveLength(2);
  expect(screen.getByText("source_object_heuristic")).toBeInTheDocument();
  expect(
    (screen.getByRole("textbox", {
      name: "Structured payload JSON",
    }) as HTMLTextAreaElement).value,
  ).toContain("table 5-6");
});

it("opens candidate PDF pages from the review panel", async () => {
  const onOpenPdfPage = vi.fn();
  const user = userEvent.setup();

  renderApp(
    <StructuredEvidenceReviewPanel
      client={client()}
      onOpenPdfPage={onOpenPdfPage}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "Open page 112" }));

  expect(onOpenPdfPage).toHaveBeenCalledWith({
    bookId: "core-rules",
    title: "Core Rules",
    pageNumber: 112,
    viewMode: "single",
  });
});

it("approves corrects and rejects candidates through the API", async () => {
  const fakeClient = client();
  const user = userEvent.setup();

  renderApp(
    <StructuredEvidenceReviewPanel
      client={fakeClient}
      onOpenPdfPage={vi.fn()}
    />,
  );

  await user.click(await screen.findByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(fakeClient.approveStructuredCandidate).toHaveBeenCalledWith(
      "candidate-1",
      { reviewer: "local" },
    ),
  );

  await user.click(await screen.findByRole("button", { name: "Correct" }));
  await waitFor(() =>
    expect(fakeClient.correctStructuredCandidate).toHaveBeenCalledWith(
      "candidate-1",
      expect.objectContaining({
        payload_json: expect.objectContaining({ schema_version: 1 }),
        reviewer: "local",
      }),
    ),
  );

  await user.click(await screen.findByRole("button", { name: "Reject" }));
  await waitFor(() =>
    expect(fakeClient.rejectStructuredCandidate).toHaveBeenCalledWith(
      "candidate-1",
      { reviewer: "local" },
    ),
  );
});

it("validates edited JSON before submitting a correction", async () => {
  const fakeClient = client();
  const user = userEvent.setup();

  renderApp(
    <StructuredEvidenceReviewPanel
      client={fakeClient}
      onOpenPdfPage={vi.fn()}
    />,
  );

  const editor = await screen.findByRole("textbox", {
    name: "Structured payload JSON",
  });
  fireEvent.change(editor, { target: { value: "{broken" } });
  await user.click(screen.getByRole("button", { name: "Correct" }));

  expect(await screen.findByText("Payload JSON is invalid.")).toBeInTheDocument();
  expect(fakeClient.correctStructuredCandidate).not.toHaveBeenCalled();
});

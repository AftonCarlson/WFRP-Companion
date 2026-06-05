import { BookOpen } from "lucide-react";
import { useState } from "react";

import type { ApiClient } from "../../lib/apiClient";
import { apiClient } from "../../lib/apiClient";
import { errorMessage } from "../../lib/apiError";
import type { SearchHitResponse } from "../../types/api";

export type SearchResultCardProps = {
  client?: ApiClient;
  hit: SearchHitResponse;
  onOpenPdfPage: (hit: SearchHitResponse) => void;
};

export function SearchResultCard({
  client = apiClient,
  hit,
  onOpenPdfPage,
}: SearchResultCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [fullText, setFullText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function toggleFullText() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (fullText !== null) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const pageText = await client.getPageText(hit.book_id, hit.pdf_page_number);
      setFullText(pageText.text);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <article className="search-result-card">
      <div className="search-result-card__header">
        <strong>
          {hit.title} PDF page {hit.pdf_page_number}
          {visiblePrintedPage(hit) ? ` (printed page ${hit.page_label})` : null}
        </strong>
        <button
          aria-label={openPdfPageLabel(hit)}
          className="search-result-card__open"
          onClick={() => onOpenPdfPage(hit)}
          type="button"
        >
          <BookOpen aria-hidden="true" size={15} />
        </button>
      </div>
      <p>{hit.snippet}</p>
      <div className="search-result-card__actions">
        <button onClick={toggleFullText} type="button">
          {expanded ? "Hide full text" : "Show full text"}
        </button>
        <button disabled type="button">
          Ask agent
        </button>
      </div>
      {expanded ? (
        <div className="search-result-card__full-text">
          {loading ? "Loading page text..." : null}
          {error ? <span className="inline-error">{error}</span> : null}
          {fullText ? fullText : null}
        </div>
      ) : null}
    </article>
  );
}

function visiblePrintedPage(hit: SearchHitResponse) {
  return hit.page_label && hit.page_label !== String(hit.pdf_page_number);
}

function openPdfPageLabel(hit: SearchHitResponse) {
  if (visiblePrintedPage(hit)) {
    return `Open ${hit.title} PDF page ${hit.pdf_page_number} (printed page ${hit.page_label})`;
  }
  return `Open ${hit.title} PDF page ${hit.pdf_page_number}`;
}

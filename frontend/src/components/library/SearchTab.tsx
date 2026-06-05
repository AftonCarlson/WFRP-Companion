import { useRef, useState } from "react";

import type { ApiClient } from "../../lib/apiClient";
import { apiClient } from "../../lib/apiClient";
import { errorMessage } from "../../lib/apiError";
import { groupSearchHits } from "../../lib/grouping";
import type { SearchHitResponse } from "../../types/api";
import { SearchResultGroup } from "./SearchResultGroup";

export type SearchTabProps = {
  client?: ApiClient;
  onOpenPdfPage: (hit: SearchHitResponse) => void;
};

export function SearchTab({ client = apiClient, onOpenPdfPage }: SearchTabProps) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHitResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError(null);
    try {
      const response = await client.searchExact(trimmed, {
        signal: controller.signal,
      });
      setHits(response.hits);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) {
        setError(errorMessage(caught));
      }
    } finally {
      if (request.current === controller) {
        setLoading(false);
      }
    }
  }

  return (
    <div className="search-tab">
      <form onSubmit={handleSubmit}>
        <input
          aria-label="Search book text"
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder="Search indexed text..."
          type="search"
          value={query}
        />
        <button disabled={loading || query.trim().length === 0} type="submit">
          Search
        </button>
      </form>
      {error ? <div className="inline-error">{error}</div> : null}
      <div className="search-tab__results">
        {loading ? <div className="muted">Searching...</div> : null}
        {!loading && hits.length === 0 ? (
          <div className="muted">No search results yet.</div>
        ) : null}
        {groupSearchHits(hits).map((group) => (
          <SearchResultGroup
            client={client}
            group={group}
            key={group.bookId}
            onOpenPdfPage={onOpenPdfPage}
          />
        ))}
      </div>
    </div>
  );
}

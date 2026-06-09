import type { ApiClient } from "../../lib/apiClient";
import type { SearchResultGroup as SearchResultGroupModel } from "../../lib/grouping";
import type { SearchHitResponse } from "../../types/api";
import { SearchResultCard } from "./SearchResultCard";

export type SearchResultGroupProps = {
  client?: ApiClient;
  group: SearchResultGroupModel;
  onOpenPdfPage: (hit: SearchHitResponse) => void;
};

export function SearchResultGroup({
  client,
  group,
  onOpenPdfPage,
}: SearchResultGroupProps) {
  return (
    <section className="search-result-group">
      <h3>
        {group.title}
        <small>{group.hits.length} hits</small>
      </h3>
      {group.hits.map((hit) => (
        <SearchResultCard
          client={client}
          hit={hit}
          key={hit.page_id}
          onOpenPdfPage={onOpenPdfPage}
        />
      ))}
    </section>
  );
}

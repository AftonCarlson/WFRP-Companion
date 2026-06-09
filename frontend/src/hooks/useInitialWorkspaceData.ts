import { useEffect, useState } from "react";

import { apiClient, type ApiClient } from "../lib/apiClient";
import { errorMessage } from "../lib/apiError";
import type {
  BookSummaryResponse,
  SourceSetBookResponse,
  SourceSetsResponse,
} from "../types/api";

export type InitialWorkspaceData = {
  books: BookSummaryResponse[];
  sourceSets: SourceSetsResponse["source_sets"];
  activeSourceSetId: string | null;
  sourceSetBooks: SourceSetBookResponse[];
};

export type InitialWorkspaceState = {
  data: InitialWorkspaceData | null;
  error: string | null;
  loading: boolean;
};

export function useInitialWorkspaceData(
  client: ApiClient = apiClient,
): InitialWorkspaceState {
  const [state, setState] = useState<InitialWorkspaceState>({
    data: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      setState({ data: null, error: null, loading: true });
      try {
        await client.getHealth({ signal: controller.signal });
        const [booksResponse, sourceSetsResponse] = await Promise.all([
          client.listBooks({ signal: controller.signal }),
          client.listSourceSets({ signal: controller.signal }),
        ]);
        const activeSourceSetId = sourceSetsResponse.active_source_set_id;
        const sourceSetBooks = activeSourceSetId
          ? (
              await client.listSourceSetBooks(activeSourceSetId, {
                signal: controller.signal,
              })
            ).books
          : [];
        setState({
          data: {
            books: booksResponse.books,
            sourceSets: sourceSetsResponse.source_sets,
            activeSourceSetId,
            sourceSetBooks,
          },
          error: null,
          loading: false,
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setState({ data: null, error: errorMessage(error), loading: false });
      }
    }

    void load();
    return () => controller.abort();
  }, [client]);

  return state;
}

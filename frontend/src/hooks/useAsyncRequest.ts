import { useCallback, useState } from "react";

import { errorMessage } from "../lib/apiError";

export type AsyncState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
};

export function useAsyncRequest<T>() {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: false,
  });

  const run = useCallback(async (request: () => Promise<T>) => {
    setState({ data: null, error: null, loading: true });
    try {
      const data = await request();
      setState({ data, error: null, loading: false });
      return data;
    } catch (error) {
      setState({ data: null, error: errorMessage(error), loading: false });
      throw error;
    }
  }, []);

  return { ...state, run };
}

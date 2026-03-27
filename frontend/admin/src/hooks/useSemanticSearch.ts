import { useCallback, useEffect, useState } from "react";
import { postSearch } from "../api/metrics";
import { useProject } from "../context/ProjectContext";

export interface SearchResult {
  text: string;
  source: string;
  date: string;
  _distance: number;
  metadata?: string;
}

export interface SearchResponse {
  query: string;
  table: string;
  results: SearchResult[];
  error?: string;
}

export function useSemanticSearch() {
  const { projectId } = useProject();
  const [query, setQuery] = useState("");
  const [table, setTable] = useState("knowledge");
  const [topK, setTopK] = useState<number>(5);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setResponse(null);
    setError("");
  }, [projectId]);

  const submit = useCallback(async () => {
    if (!query.trim()) {
      return;
    }

    setError("");
    setLoading(true);

    try {
      const result = await postSearch<SearchResponse>(query, table, topK);
      setResponse(result);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setLoading(false);
    }
  }, [query, table, topK]);

  return {
    canSubmit: query.trim() !== "" && !loading,
    error,
    loading,
    query,
    response,
    setQuery,
    setTable,
    setTopK,
    submit,
    table,
    topK,
  };
}

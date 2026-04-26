import { fetchJson, apiUrl, projectUrl, post, getActiveProjectId } from "./common";

export interface MetricsTimingBucket {
  count: number;
  sum_ms: number;
  max_ms: number;
  avg_ms: number;
}

export interface MetricsSnapshot {
  counters: Record<string, number>;
  timings: Record<string, MetricsTimingBucket>;
  counter_count: number;
  timing_count: number;
}

export async function fetchHealth<T = Record<string, unknown>>() {
  return fetchJson<T>(apiUrl("/health"));
}

export async function fetchHealthDetailed<T = Record<string, unknown>>() {
  return fetchJson<T>(projectUrl("/health/detailed"));
}

export function postEmbed<T = Record<string, unknown>>(texts: string[]) {
  return post<T>("/embed", { texts });
}

export function postSearch<T = Record<string, unknown>>(query: string, table = "knowledge", topK = 5) {
  return post<T>("/search", { query, table, top_k: topK, project_id: getActiveProjectId() });
}

export async function fetchMetrics() {
  return fetchJson<MetricsSnapshot>(apiUrl("/metrics"));
}

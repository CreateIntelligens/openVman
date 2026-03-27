import { fetchJson, projectUrl, post, jsonRequest, MEMORIES_PATH, getActiveProjectId } from "./common";

export interface MemoryRecord {
  text: string;
  source: string;
  date: string;
  metadata?: string;
}

export interface MemoriesListResponse {
  memories: MemoryRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface MemoryMaintenanceResponse {
  status: string;
  summaries_written?: number;
  records_before?: number;
  records_after?: number;
  deduped?: number;
  [key: string]: unknown;
}

export async function fetchMemories(page = 1, pageSize = 20) {
  return fetchJson<MemoriesListResponse>(
    projectUrl("/memories", { page: String(page), page_size: String(pageSize) }),
  );
}

export function deleteMemory(text: string) {
  return jsonRequest<{ status: string }>(
    "DELETE",
    MEMORIES_PATH,
    { project_id: getActiveProjectId(), text },
  );
}

export function postAddMemory(
  text: string,
  source = "user",
  metadata: Record<string, unknown> = {},
) {
  return post<Record<string, unknown>>(MEMORIES_PATH, { text, source, metadata, project_id: getActiveProjectId() });
}

export function runMemoryMaintenance() {
  return post<MemoryMaintenanceResponse>(`${MEMORIES_PATH}/maintain`, {
    project_id: getActiveProjectId(),
  });
}

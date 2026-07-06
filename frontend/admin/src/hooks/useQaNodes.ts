import { useCallback, useState } from "react";

import {
  apiUrl,
  del,
  fetchJson,
  get,
  getActiveProjectId,
} from "../api/common";
import { errorMessage } from "../utils/errorMessage";

export interface QaEntry {
  question: string;
  source_path: string;
  hidden: boolean;
  image_id: string | null;
}

export interface QaNode {
  node_id: string;
  label: string;
  parent_ids: string[];
  child_ids: string[];
  order: number;
  hidden: boolean;
  qa_entries: QaEntry[];
  children?: QaNode[];
}

export interface MergedQaItem {
  index?: string;
  q: string;
  a: string;
  img?: string;
  url?: string;
  source_file: string;
  hidden?: boolean;
}

function qaProjectUrl(path: string): string {
  return apiUrl(path, { project_id: getActiveProjectId() });
}

function nodePath(id: string, suffix = ""): string {
  return `/knowledge/qa/nodes/${encodeURIComponent(id)}${suffix}`;
}

function qaJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(qaProjectUrl(path), {
    method,
    ...(body !== undefined && {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  });
}

function qaFormData<T>(path: string, file: File): Promise<T> {
  const formData = new FormData();
  formData.append("file", file);
  return fetchJson<T>(qaProjectUrl(path), { method: "POST", body: formData });
}

export function useQaNodes() {
  const [nodesTree, setNodesTree] = useState<QaNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTree = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await get<QaNode[]>("/knowledge/qa/nodes", { project_id: getActiveProjectId() });
      setNodesTree(data);
      return data;
    } catch (error: unknown) {
      setError(errorMessage(error, "Failed to fetch QA nodes tree"));
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  // Wraps a request with shared error handling; set refetch to also reload the
  // tree (and reflect the mutation) after a successful call.
  const run = useCallback(
    async <T,>(
      fn: () => Promise<T>,
      fallback: string,
      refetch = false,
    ): Promise<T> => {
      setError(null);
      try {
        const data = await fn();
        if (refetch) await fetchTree();
        return data;
      } catch (error: unknown) {
        setError(errorMessage(error, fallback));
        throw error;
      }
    },
    [fetchTree],
  );

  const createNode = useCallback((
    nodeId: string,
    label: string,
    parentIds?: string[],
    childIds?: string[],
    order?: number,
    hidden?: boolean
  ) => run(() => qaJson<QaNode>("/knowledge/qa/nodes", "POST", {
    node_id: nodeId,
    label,
    parent_ids: parentIds ?? [],
    child_ids: childIds ?? [],
    order: order ?? 1.0,
    hidden: Boolean(hidden),
  }), "Failed to create QA node", true), [run]);

  const updateNode = useCallback((
    id: string,
    updates: { label?: string; hidden?: boolean }
  ) => run(() => qaJson<QaNode>(nodePath(id), "PATCH", updates),
    "Failed to update QA node", true), [run]);

  const deleteNode = useCallback((id: string) => run(
    () => del<{ status: string }>(nodePath(id)),
    "Failed to delete QA node", true), [run]);

  const moveNode = useCallback((id: string, parentIds: string[]) => run(
    () => qaJson<QaNode>(nodePath(id, "/move"), "POST", { new_parent_ids: parentIds }),
    "Failed to move QA node", true), [run]);

  const reorderNode = useCallback((id: string, siblingIdsOrdered: string[]) => run(
    () => qaJson<QaNode>(nodePath(id, "/reorder"), "POST", { sibling_ids_ordered: siblingIdsOrdered }),
    "Failed to reorder QA node", true), [run]);

  const fetchMergedQa = useCallback((id: string) => run(
    () => get<MergedQaItem[]>(nodePath(id, "/merged")),
    "Failed to fetch merged QA entries"), [run]);

  const saveMergedQa = useCallback((id: string, rows: MergedQaItem[]) => run(
    () => qaJson<{ status: string }>(nodePath(id, "/merged"), "PUT", rows),
    "Failed to save merged QA entries", true), [run]);

  const uploadImage = useCallback((file: File) => run(
    () => qaFormData<{ image_id: string }>("/knowledge/qa/images", file),
    "Failed to upload image"), [run]);

  const deleteImage = useCallback((id: string) => run(
    () => del<{ status: string }>(`/knowledge/qa/images/${encodeURIComponent(id)}`),
    "Failed to delete image"), [run]);

  const cleanupImages = useCallback(() => run(
    () => qaJson<{ deleted_files: string[] }>("/knowledge/qa/images/cleanup-unused", "POST"),
    "Failed to cleanup images"), [run]);

  const adoptSource = useCallback((path: string, parentId?: string) => run(
    () => qaJson<{ node_id: string }>("/knowledge/qa/nodes/adopt-source", "POST", { path, parent_id: parentId }),
    "Failed to adopt QA source", true), [run]);

  const ingestSource = useCallback((id: string, path: string) => run(
    () => qaJson<{ added: number }>(nodePath(id, "/ingest-source"), "POST", { path }),
    "Failed to ingest QA source", true), [run]);

  return {
    nodesTree,
    loading,
    error,
    fetchTree,
    createNode,
    updateNode,
    deleteNode,
    moveNode,
    reorderNode,
    fetchMergedQa,
    saveMergedQa,
    uploadImage,
    deleteImage,
    cleanupImages,
    adoptSource,
    ingestSource,
  };
}

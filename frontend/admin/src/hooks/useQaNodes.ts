import { useCallback, useEffect, useRef, useState } from "react";

import {
  apiUrl,
  fetchJson,
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

function qaProjectUrl(path: string, projectId: string): string {
  return apiUrl(path, { project_id: projectId });
}

function nodePath(id: string, suffix = ""): string {
  return `/knowledge/qa/nodes/${encodeURIComponent(id)}${suffix}`;
}

function qaJson<T>(
  projectId: string,
  path: string,
  method: string,
  body?: unknown,
): Promise<T> {
  return fetchJson<T>(qaProjectUrl(path, projectId), {
    method,
    ...(body !== undefined && {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  });
}

function qaFormData<T>(
  projectId: string,
  path: string,
  file: File,
): Promise<T> {
  const formData = new FormData();
  formData.append("file", file);
  return fetchJson<T>(qaProjectUrl(path, projectId), {
    method: "POST",
    body: formData,
  });
}

export function useQaNodes(projectId = getActiveProjectId()) {
  const [treeState, setTreeState] = useState<{
    projectId: string;
    nodes: QaNode[];
  }>(() => ({ projectId, nodes: [] }));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeProjectRef = useRef(projectId);
  activeProjectRef.current = projectId;
  const nodesTree = treeState.projectId === projectId ? treeState.nodes : [];

  useEffect(() => {
    setTreeState({ projectId, nodes: [] });
    setLoading(false);
    setError(null);
  }, [projectId]);

  const fetchTree = useCallback(async () => {
    const requestedProjectId = projectId;
    setLoading(true);
    setError(null);
    try {
      const data = await qaJson<QaNode[]>(
        requestedProjectId,
        "/knowledge/qa/nodes",
        "GET",
      );
      if (activeProjectRef.current !== requestedProjectId) return [];
      setTreeState({ projectId: requestedProjectId, nodes: data });
      return data;
    } catch (error: unknown) {
      if (activeProjectRef.current === requestedProjectId) {
        setError(errorMessage(error, "Failed to fetch QA nodes tree"));
      }
      throw error;
    } finally {
      if (activeProjectRef.current === requestedProjectId) setLoading(false);
    }
  }, [projectId]);

  // Wraps a request with shared error handling; set refetch to also reload the
  // tree (and reflect the mutation) after a successful call.
  const run = useCallback(
    async <T,>(
      fn: () => Promise<T>,
      fallback: string,
      refetch = false,
    ): Promise<T> => {
      if (activeProjectRef.current === projectId) setError(null);
      try {
        const data = await fn();
        if (refetch && activeProjectRef.current === projectId) {
          await fetchTree();
        }
        return data;
      } catch (error: unknown) {
        if (activeProjectRef.current === projectId) {
          setError(errorMessage(error, fallback));
        }
        throw error;
      }
    },
    [fetchTree, projectId],
  );

  const createNode = useCallback(
    (
      nodeId: string,
      label: string,
      parentIds?: string[],
      childIds?: string[],
      order?: number,
      hidden?: boolean,
    ) => run(
      () => qaJson<QaNode>(projectId, "/knowledge/qa/nodes", "POST", {
        node_id: nodeId,
        label,
        parent_ids: parentIds ?? [],
        child_ids: childIds ?? [],
        order: order ?? 1.0,
        hidden: Boolean(hidden),
      }),
      "Failed to create QA node",
      true,
    ),
    [projectId, run],
  );

  const updateNode = useCallback(
    (id: string, updates: { label?: string; hidden?: boolean }) => run(
      () => qaJson<QaNode>(projectId, nodePath(id), "PATCH", updates),
      "Failed to update QA node",
      true,
    ),
    [projectId, run],
  );

  const deleteNode = useCallback(
    (id: string) => run(
      () => qaJson<{ status: string }>(projectId, nodePath(id), "DELETE"),
      "Failed to delete QA node",
      true,
    ),
    [projectId, run],
  );

  const moveNode = useCallback(
    (id: string, parentIds: string[]) => run(
      () => qaJson<QaNode>(projectId, nodePath(id, "/move"), "POST", {
        new_parent_ids: parentIds,
      }),
      "Failed to move QA node",
      true,
    ),
    [projectId, run],
  );

  const reorderNode = useCallback(
    (id: string, siblingIdsOrdered: string[]) => run(
      () => qaJson<QaNode>(projectId, nodePath(id, "/reorder"), "POST", {
        sibling_ids_ordered: siblingIdsOrdered,
      }),
      "Failed to reorder QA node",
      true,
    ),
    [projectId, run],
  );

  const fetchMergedQa = useCallback(
    (id: string) => run(
      () => qaJson<MergedQaItem[]>(
        projectId,
        nodePath(id, "/merged"),
        "GET",
      ),
      "Failed to fetch merged QA entries",
    ),
    [projectId, run],
  );

  const saveMergedQa = useCallback(
    (id: string, rows: MergedQaItem[]) => run(
      () => qaJson<{ status: string }>(
        projectId,
        nodePath(id, "/merged"),
        "PUT",
        rows,
      ),
      "Failed to save merged QA entries",
      true,
    ),
    [projectId, run],
  );

  const uploadImage = useCallback(
    (file: File) => run(
      () => qaFormData<{ image_id: string }>(
        projectId,
        "/knowledge/qa/images",
        file,
      ),
      "Failed to upload image",
    ),
    [projectId, run],
  );

  const deleteImage = useCallback(
    (id: string) => run(
      () => qaJson<{ status: string }>(
        projectId,
        `/knowledge/qa/images/${encodeURIComponent(id)}`,
        "DELETE",
      ),
      "Failed to delete image",
    ),
    [projectId, run],
  );

  const cleanupImages = useCallback(
    () => run(
      () => qaJson<{ deleted_files: string[] }>(
        projectId,
        "/knowledge/qa/images/cleanup-unused",
        "POST",
      ),
      "Failed to cleanup images",
    ),
    [projectId, run],
  );

  const adoptSource = useCallback(
    (path: string, parentId?: string) => run(
      () => qaJson<{ node_id: string }>(
        projectId,
        "/knowledge/qa/nodes/adopt-source",
        "POST",
        { path, parent_id: parentId },
      ),
      "Failed to adopt QA source",
      true,
    ),
    [projectId, run],
  );

  const ingestSource = useCallback(
    (id: string, path: string) => run(
      () => qaJson<{ added: number }>(
        projectId,
        nodePath(id, "/ingest-source"),
        "POST",
        { path },
      ),
      "Failed to ingest QA source",
      true,
    ),
    [projectId, run],
  );

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

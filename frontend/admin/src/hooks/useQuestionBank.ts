import { useCallback, useEffect, useRef, useState } from "react";

import { fetchAllQuestions, type QaAllQuestions } from "../api/knowledge";

export function useQuestionBank(projectId: string, revision: number) {
  const [state, setState] = useState<{
    projectId: string;
    data: QaAllQuestions | null;
    loading: boolean;
    error: boolean;
    refreshFailed: boolean;
  }>({ projectId, data: null, loading: true, error: false, refreshFailed: false });
  const generation = useRef(0);
  const activeProject = useRef(projectId);
  activeProject.current = projectId;
  const refresh = useCallback(async (afterWrite = false) => {
    if (activeProject.current !== projectId) return;
    const request = ++generation.current;
    const isCurrent = () => activeProject.current === projectId && generation.current === request;
    setState((previous) => ({
      projectId,
      data: previous.projectId === projectId ? previous.data : null,
      loading: true,
      error: false,
      refreshFailed: previous.projectId === projectId && previous.refreshFailed,
    }));
    try {
      const data = await fetchAllQuestions(projectId);
      if (isCurrent()) setState({ projectId, data, loading: false, error: false, refreshFailed: false });
    } catch {
      if (isCurrent()) {
        setState((previous) => ({
          ...previous,
          loading: false,
          error: !afterWrite,
          refreshFailed: afterWrite || previous.refreshFailed,
        }));
      }
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
    return () => { generation.current += 1; };
  }, [refresh, revision]);

  return {
    data: state.projectId === projectId ? state.data : null,
    loading: state.projectId !== projectId || state.loading,
    error: state.projectId === projectId && state.error,
    refreshFailed: state.projectId === projectId && state.refreshFailed,
    refresh,
  };
}

import { useCallback, useEffect, useState } from "react";
import { saveProjectFeatures, type ProjectFeatures } from "../api/knowledge";
import { createProject, deleteProject, fetchProjects, setProjectVendor, type ProjectSummary } from "../api/projects";
import { useProject } from "../context/ProjectContext";
import { useStatusState } from "./useStatusState";

export function useProjectsAdmin() {
  const { refreshProjects, setProjectId, projectId: currentProjectId } = useProject();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [newProjectLabel, setNewProjectLabel] = useState("");
  const [newProjectVendor, setNewProjectVendor] = useState("");
  // 新專案預設兩項都關；建立時勾了才在建好後打開。
  const [newProjectFeatures, setNewProjectFeatures] = useState<ProjectFeatures>({
    memory_enabled: false,
    graph_enabled: false,
  });
  const [lastCreatedId, setLastCreatedId] = useState("");
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState("");
  const [deleteTargetId, setDeleteTargetId] = useState("");
  const { status, setStatus, setErrorStatus } = useStatusState();

  const trimmedNewProjectLabel = newProjectLabel.trim();
  const canCreateProject = trimmedNewProjectLabel !== "" && !creating;

  const loadProjects = useCallback(async () => {
    setLoading(true);

    try {
      const response = await fetchProjects();
      setProjects(response.projects);
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setLoading(false);
    }
  }, [setErrorStatus]);

  const refreshProjectList = useCallback(async () => {
    await refreshProjects();
    await loadProjects();
  }, [loadProjects, refreshProjects]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const handleCreate = useCallback(async () => {
    if (!canCreateProject) {
      return;
    }

    setCreating(true);
    setStatus(null);
    setLastCreatedId("");

    try {
      const result = await createProject(trimmedNewProjectLabel, newProjectVendor.trim() || undefined);
      const enabled = Object.fromEntries(
        Object.entries(newProjectFeatures).filter(([, on]) => on),
      ) as Partial<ProjectFeatures>;
      let featuresSaved = true;
      if (Object.keys(enabled).length > 0) {
        try {
          await saveProjectFeatures(result.project_id, enabled);
        } catch {
          featuresSaved = false;
        }
      }
      setNewProjectLabel("");
      setNewProjectVendor("");
      setNewProjectFeatures({ memory_enabled: false, graph_enabled: false });
      setLastCreatedId(result.project_id);
      setStatus(featuresSaved
        ? {
          type: "success",
          message: `專案「${trimmedNewProjectLabel}」已建立（ID: ${result.project_id}）`,
        }
        : {
          type: "error",
          message: `專案「${trimmedNewProjectLabel}」已建立，但記憶與知識圖譜沒有打開。請在專案卡片按「回答功能」再設定一次。`,
        });
      await refreshProjectList();
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setCreating(false);
    }
  }, [
    canCreateProject,
    newProjectFeatures,
    newProjectVendor,
    refreshProjectList,
    setErrorStatus,
    setStatus,
    trimmedNewProjectLabel,
  ]);

  async function handleSetVendor(projectId: string, vendorName: string | null) {
    await setProjectVendor(projectId, vendorName);
    setStatus({ type: "success", message: "已更新所屬廠商。" });
    await refreshProjectList();
  }

  const handleDelete = useCallback(async (projectId: string) => {
    setDeleteTargetId("");
    if (deletingId) {
      return;
    }

    setDeletingId(projectId);
    setStatus(null);

    try {
      await deleteProject(projectId);
      setStatus({ type: "success", message: `專案 "${projectId}" 已刪除` });
      if (projectId === currentProjectId) {
        setProjectId("default");
      }
      await refreshProjectList();
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setDeletingId("");
    }
  }, [currentProjectId, deletingId, refreshProjectList, setErrorStatus, setProjectId]);

  return {
    canCreateProject,
    creating,
    deleteTargetId,
    deletingId,
    handleCreate,
    handleDelete,
    handleSetVendor,
    lastCreatedId,
    loadProjects,
    loading,
    newProjectLabel,
    newProjectFeatures,
    newProjectVendor,
    projects,
    setDeleteTargetId,
    setNewProjectFeatures,
    setNewProjectLabel,
    setNewProjectVendor,
    setStatus,
    status,
  };
}

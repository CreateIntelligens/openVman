import { useCallback, useEffect, useState } from "react";
import { createProject, deleteProject, fetchProjects, type ProjectSummary } from "../api/projects";
import { useProject } from "../context/ProjectContext";
import { useStatusState } from "./useStatusState";

export function useProjectsAdmin() {
  const { refreshProjects, setProjectId, projectId: currentProjectId } = useProject();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [newProjectLabel, setNewProjectLabel] = useState("");
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
      const result = await createProject(trimmedNewProjectLabel);
      setNewProjectLabel("");
      setLastCreatedId(result.project_id);
      setStatus({
        type: "success",
        message: `專案「${trimmedNewProjectLabel}」已建立（ID: ${result.project_id}）`,
      });
      await refreshProjectList();
    } catch (error) {
      setErrorStatus(error);
    } finally {
      setCreating(false);
    }
  }, [canCreateProject, refreshProjectList, setErrorStatus, trimmedNewProjectLabel]);

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
    lastCreatedId,
    loadProjects,
    loading,
    newProjectLabel,
    projects,
    setDeleteTargetId,
    setNewProjectLabel,
    status,
  };
}

import ConfirmModal from "../components/ConfirmModal";
import StatusAlert from "../components/StatusAlert";
import { useProjectsAdmin } from "../hooks/useProjectsAdmin";

export default function Projects() {
  const {
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
  } = useProjectsAdmin();

  return (
    <div className="page-scroll">
      <header className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 bg-white/80 dark:bg-background-dark/80 backdrop-blur-md border-b border-slate-200 dark:border-primary/10 transition-colors">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Projects</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            管理多專案隔離，每個專案有獨立的 knowledge、persona、memory 空間。
          </p>
        </div>
        <div className="text-xs text-slate-400 dark:text-slate-500">
          {projects.length} project{projects.length !== 1 ? "s" : ""}
        </div>
      </header>

      <div className="p-8 space-y-8">
        {status && <StatusAlert type={status.type} message={status.message} />}

        {/* Create new project */}
        <section className="rounded-3xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 p-6 shadow-sm dark:shadow-none transition-all">
          <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-400 dark:text-slate-500">
            New Project
          </p>
          <h3 className="mt-2 text-lg font-bold text-slate-900 dark:text-white">建立新專案</h3>
          <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label className="mb-1 block text-xs text-slate-500 dark:text-slate-400">專案名稱</label>
              <input
                type="text"
                value={newProjectLabel}
                onChange={(e) => setNewProjectLabel(e.target.value)}
                placeholder="例：My Project 或 慧誠醫院"
                className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-primary/40 focus:outline-none shadow-sm dark:shadow-none transition-all"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    void handleCreate();
                  }
                }}
              />
            </div>
            <button
              onClick={handleCreate}
              disabled={!canCreateProject}
              className="rounded-xl bg-primary px-6 py-3 font-bold text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {creating ? "Creating..." : "Create"}
            </button>
          </div>
          {lastCreatedId && (
            <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
              自動產生的 ID：<code className="rounded bg-slate-200 dark:bg-slate-800 px-1.5 py-0.5 font-mono text-primary">{lastCreatedId}</code>
            </p>
          )}
        </section>

        {/* Project list */}
        <section className="rounded-3xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 p-6 shadow-sm dark:shadow-none transition-all">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-400 dark:text-slate-500">
                All Projects
              </p>
              <h3 className="mt-2 text-lg font-bold text-slate-900 dark:text-white">專案列表</h3>
            </div>
            <button
              onClick={() => void loadProjects()}
              disabled={loading}
              className="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600 hover:text-slate-900 dark:hover:text-white transition-all shadow-sm dark:shadow-none disabled:opacity-50"
            >
              {loading ? "Loading..." : "Refresh"}
            </button>
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <div
                key={project.project_id}
                className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950/50 p-5 flex flex-col gap-4 shadow-sm hover:shadow-md dark:hover:shadow-none transition-all"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h4 className="text-base font-bold text-slate-900 dark:text-white truncate">
                      {project.label}
                    </h4>
                    <p className="mt-1 text-xs text-slate-400 dark:text-slate-500 font-mono">
                      {project.project_id}
                    </p>
                  </div>
                  {project.project_id === "default" && (
                    <span className="shrink-0 rounded-full bg-primary/10 border border-primary/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-primary">
                      Default
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 px-3 py-2">
                    <p className="text-[10px] uppercase tracking-[0.2em] text-slate-400 dark:text-slate-500">Docs</p>
                    <p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{project.document_count}</p>
                  </div>
                  <div className="rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 px-3 py-2">
                    <p className="text-[10px] uppercase tracking-[0.2em] text-slate-400 dark:text-slate-500">Personas</p>
                    <p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{project.persona_count}</p>
                  </div>
                </div>

                {project.project_id !== "default" && (
                  <button
                    onClick={() => setDeleteTargetId(project.project_id)}
                    disabled={!!deletingId}
                    className="mt-auto rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-2 text-xs font-medium text-red-400 hover:bg-red-500/10 hover:border-red-500/30 transition-colors disabled:opacity-50"
                  >
                    {deletingId === project.project_id ? "Deleting..." : "Delete Project"}
                  </button>
                )}
              </div>
            ))}

            {!projects.length && !loading && (
              <p className="col-span-full text-sm text-slate-400 dark:text-slate-500">
                沒有專案。建立第一個專案開始使用。
              </p>
            )}
          </div>
        </section>
      </div>

      <ConfirmModal
        open={deleteTargetId !== ""}
        title="Delete Project"
        message={`確定要刪除專案「${deleteTargetId}」嗎？\n\n此操作會刪除該專案的所有 knowledge、persona 和 memory 資料，且無法復原。`}
        confirmLabel="Delete"
        danger
        onConfirm={() => handleDelete(deleteTargetId)}
        onCancel={() => setDeleteTargetId("")}
      />
    </div>
  );
}

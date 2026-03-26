import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchTools,
  toggleSkill,
  deleteSkill,
  reloadAllSkills,
  type ToolInfo,
  type SkillInfo,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import ConfirmModal from "../components/ConfirmModal";
import CreateSkillForm from "../components/tools/CreateSkillForm";
import SkillCard from "../components/tools/SkillCard";
import SkillEditor from "../components/tools/SkillEditor";
import ToolTable from "../components/tools/ToolTable";

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function Tools() {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [skillTools, setSkillTools] = useState<ToolInfo[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [editingSkillId, setEditingSkillId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SkillInfo | null>(null);
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    setLoading(true);
    fetchTools()
      .then((data) => {
        setTools(data.tools);
        setSkillTools(data.skill_tools ?? []);
        setSkills(data.skills);
        setError("");
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleToggle = (skill: SkillInfo) => {
    setTogglingIds((prev) => new Set(prev).add(skill.id));
    toggleSkill(skill.id)
      .then(() => load())
      .catch((e) => setError(String(e)))
      .finally(() =>
        setTogglingIds((prev) => {
          const next = new Set(prev);
          next.delete(skill.id);
          return next;
        }),
      );
  };

  const handleReloadAll = () => {
    setReloading(true);
    reloadAllSkills()
      .then(() => load())
      .catch((e) => setError(String(e)))
      .finally(() => setReloading(false));
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    deleteSkill(id)
      .then(() => {
        if (editingSkillId === id) setEditingSkillId(null);
        load();
      })
      .catch((e) => setError(String(e)));
  };

  const skillNameById = useMemo(
    () => Object.fromEntries(skills.map((skill) => [skill.id, skill.name])),
    [skills],
  );

  return (
    <div className="page-scroll">
      {/* Header */}
      <header className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <div>
          <h2 className="text-2xl font-bold">工具與技能</h2>
          <p className="text-sm text-slate-400">
            管理技能插件及查看已註冊工具
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleReloadAll}
            disabled={reloading}
            className="flex items-center gap-2 px-4 py-2 border border-slate-700 hover:border-primary/40 text-slate-300 hover:text-primary rounded-lg font-bold transition-all text-sm disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">sync</span>
            {reloading ? "重新載入中..." : "重新載入所有技能"}
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg font-bold transition-all shadow-lg shadow-primary/20 disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            <span>{loading ? "載入中..." : "重新整理"}</span>
          </button>
        </div>
      </header>

      <div className="p-8 space-y-8">
        {error && <StatusAlert type="error" message={error} />}

        {/* Skills Section */}
        <section>
          <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 px-1 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-base">extension</span>
            技能
            <span className="text-xs font-mono text-slate-600">({skills.length})</span>
          </h3>

          {skills.length === 0 && !loading && !error && (
            <p className="text-sm text-slate-500 px-1 mb-4">尚未載入任何技能。</p>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
            {skills.map((skill) => (
              <SkillCard
                key={skill.id}
                skill={skill}
                isEditing={editingSkillId === skill.id}
                isToggling={togglingIds.has(skill.id)}
                onToggle={handleToggle}
                onEdit={(skillId) => setEditingSkillId((current) => (current === skillId ? null : skillId))}
                onDelete={setDeleteTarget}
              />
            ))}
          </div>

          {/* Create Skill Form */}
          <CreateSkillForm onCreated={load} />
        </section>

        {/* Skill Editor Panel */}
        {editingSkillId && (
          <section>
            <SkillEditor
              key={editingSkillId}
              skillId={editingSkillId}
              onClose={() => setEditingSkillId(null)}
              onSaved={load}
            />
          </section>
        )}

        {/* Built-in Tools Section */}
        <section>
          <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 px-1 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-base">settings</span>
            內建工具
            <span className="text-xs font-mono text-slate-600">({tools.length})</span>
          </h3>

          {tools.length > 0 && (
            <ToolTable tools={tools} />
          )}
        </section>

        {/* Skill Tools Section */}
        {skillTools.length > 0 && (
          <section>
            <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 px-1 mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-base">extension</span>
              技能工具
              <span className="text-xs font-mono text-slate-600">({skillTools.length})</span>
            </h3>

            <ToolTable tools={skillTools} resolveSkillName={(skillId) => skillNameById[skillId]} />
          </section>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        open={!!deleteTarget}
        title="刪除技能"
        message={deleteTarget ? `確定要刪除「${deleteTarget.name}」（${deleteTarget.id}）嗎？\n\n此操作將永久移除技能目錄及其所有檔案。` : ""}
        confirmLabel="刪除"
        danger
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

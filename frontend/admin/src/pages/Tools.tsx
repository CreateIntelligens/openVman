import { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteSkill,
  fetchTools,
  reloadAllSkills,
  skillKey,
  toggleSkill,
  type SkillInfo,
  type ToolInfo,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import ConfirmModal from "../components/ConfirmModal";
import CreateSkillForm from "../components/tools/CreateSkillForm";
import SkillCard from "../components/tools/SkillCard";
import SkillEditor from "../components/tools/SkillEditor";
import ToolTable from "../components/tools/ToolTable";

interface SkillSectionProps {
  title: string;
  icon: string;
  skills: SkillInfo[];
  editingSkillId: string | null;
  togglingIds: Set<string>;
  loading: boolean;
  hasError: boolean;
  emptyMessage: string;
  onToggle: (skill: SkillInfo) => void;
  onEdit: (key: string) => void;
  onDelete: (skill: SkillInfo) => void;
  children?: React.ReactNode;
}

function SkillSection({
  title,
  icon,
  skills,
  editingSkillId,
  togglingIds,
  loading,
  hasError,
  emptyMessage,
  onToggle,
  onEdit,
  onDelete,
  children,
}: SkillSectionProps) {
  return (
    <section>
      <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 px-1 mb-4 flex items-center gap-2">
        <span className="material-symbols-outlined text-base">{icon}</span>
        {title}
        <span className="text-xs font-mono text-slate-500 dark:text-slate-600">({skills.length})</span>
      </h3>
      {skills.length === 0 && !loading && !hasError && (
        <p className="text-sm text-slate-500 px-1 mb-4">{emptyMessage}</p>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
        {skills.map((skill) => {
          const key = skillKey(skill);
          return (
            <SkillCard
              key={key}
              skill={skill}
              isEditing={editingSkillId === key}
              isToggling={togglingIds.has(key)}
              onToggle={onToggle}
              onEdit={() => onEdit(key)}
              onDelete={onDelete}
            />
          );
        })}
      </div>
      {children}
    </section>
  );
}

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
    const key = skillKey(skill);
    setTogglingIds((prev) => new Set(prev).add(key));
    toggleSkill(skill.id, {
      scope: skill.scope,
      project_id: skill.project_id ?? undefined,
    })
      .then((response) => {
        setSkills((current) =>
          current.map((s) =>
            skillKey(s) === key ? { ...s, enabled: response.enabled } : s,
          ),
        );
      })
      .catch((e) => setError(String(e)))
      .finally(() =>
        setTogglingIds((prev) => {
          const next = new Set(prev);
          next.delete(key);
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

  const busy = reloading || loading;

  const handleDelete = () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    const key = skillKey(target);
    setDeleteTarget(null);
    deleteSkill(target.id, {
      scope: target.scope,
      project_id: target.project_id ?? undefined,
    })
      .then(() => {
        if (editingSkillId === key) setEditingSkillId(null);
        setSkills((current) => current.filter((s) => skillKey(s) !== key));
      })
      .catch((e) => setError(String(e)));
  };

  const skillNameById = useMemo(
    () => Object.fromEntries(skills.map((skill) => [skill.id, skill.name])),
    [skills],
  );

  const projectSkills = useMemo(
    () => skills.filter((s) => s.scope === "project"),
    [skills],
  );
  const sharedSkills = useMemo(
    () => skills.filter((s) => !s.scope || s.scope === "shared"),
    [skills],
  );

  const editingSkill = useMemo(
    () => skills.find((s) => skillKey(s) === editingSkillId) ?? null,
    [skills, editingSkillId],
  );

  const toggleEdit = (key: string) =>
    setEditingSkillId((current) => (current === key ? null : key));

  return (
    <div className="page-scroll">
      <header className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 bg-white/80 dark:bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <div>
          <h2 className="text-2xl font-bold">工具與技能</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            管理技能插件及查看已註冊工具
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleReloadAll}
            disabled={busy}
            title="重新掃描技能檔案並刷新清單"
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg font-bold transition-all shadow-lg shadow-primary/20 disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">sync</span>
            <span>{reloading ? "重新載入中..." : loading ? "載入中..." : "重新載入"}</span>
          </button>
        </div>
      </header>

      <div className="p-8 space-y-8">
        {error && <StatusAlert type="error" message={error} />}

        <SkillSection
          title="專案技能"
          icon="folder_special"
          skills={projectSkills}
          editingSkillId={editingSkillId}
          togglingIds={togglingIds}
          loading={loading}
          hasError={!!error}
          emptyMessage="此專案尚無專屬技能。"
          onToggle={handleToggle}
          onEdit={toggleEdit}
          onDelete={setDeleteTarget}
        >
          <CreateSkillForm onCreated={load} />
        </SkillSection>

        <SkillSection
          title="共用技能"
          icon="extension"
          skills={sharedSkills}
          editingSkillId={editingSkillId}
          togglingIds={togglingIds}
          loading={loading}
          hasError={!!error}
          emptyMessage="尚未載入任何共用技能。"
          onToggle={handleToggle}
          onEdit={toggleEdit}
          onDelete={setDeleteTarget}
        />

        {editingSkill && (
          <section>
            <SkillEditor
              key={skillKey(editingSkill)}
              skillId={editingSkill.id}
              scope={editingSkill.scope}
              projectId={editingSkill.project_id ?? undefined}
              onClose={() => setEditingSkillId(null)}
              onSaved={load}
            />
          </section>
        )}

        <section>
          <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 px-1 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-base">settings</span>
            內建工具
            <span className="text-xs font-mono text-slate-500 dark:text-slate-600">({tools.length})</span>
          </h3>

          {tools.length > 0 && <ToolTable tools={tools} />}
        </section>

        {skillTools.length > 0 && (
          <section>
            <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 px-1 mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-base">extension</span>
              技能工具
              <span className="text-xs font-mono text-slate-500 dark:text-slate-600">({skillTools.length})</span>
            </h3>

            <ToolTable tools={skillTools} resolveSkillName={(skillId) => skillNameById[skillId]} />
          </section>
        )}
      </div>

      <ConfirmModal
        open={!!deleteTarget}
        title="刪除技能"
        message={deleteTarget ? `確定要刪除「${deleteTarget.name}」(${deleteTarget.id}) 嗎？\n\n此操作將永久移除技能目錄及其所有檔案。` : ""}
        confirmLabel="刪除"
        danger
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

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
import { PageHeader } from "../components/app/PageHeader";
import StatusAlert from "../components/StatusAlert";
import ConfirmModal from "../components/ConfirmModal";
import CreateSkillForm from "../components/tools/CreateSkillForm";
import { useAuth } from "../context/AuthContext";
import { useNavigationGuard } from "../context/NavigationGuardContext";
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
  /** 顯示在標題下的說明，例如共用技能為什麼只能檢視。 */
  readOnlyNotice?: string;
  canEdit: boolean;
  canToggle: boolean;
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
  readOnlyNotice,
  canEdit,
  canToggle,
  onToggle,
  onEdit,
  onDelete,
  children,
}: SkillSectionProps) {
  return (
    <section>
      <h2 className="section-title mb-4 flex items-center gap-2">
        <span aria-hidden="true" className="material-symbols-outlined text-base">{icon}</span>
        {title}
        <span className="text-xs font-mono text-content-subtle">({skills.length})</span>
      </h2>
      {readOnlyNotice && (
        <p className="text-sm text-content-muted mb-4">{readOnlyNotice}</p>
      )}
      {skills.length === 0 && !loading && !hasError && (
        <p className="text-sm text-content-subtle mb-4">{emptyMessage}</p>
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
              canEdit={canEdit}
              canToggle={canToggle}
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

// 正式環境的共用技能目錄是唯讀掛載，內容只能改 repo 再部署；後台只留給最高管理員開關。
const SHARED_NOTICE_ROOT = "共用技能會套用到所有專案。內容要更新系統才能修改，這裡只能查看，以及啟用或停用。";
const SHARED_NOTICE = "共用技能會套用到所有專案。內容要更新系統才能修改，這裡只能查看；要啟用或停用請找最高管理員。";

export default function Tools() {
  const { requestNavigation } = useNavigationGuard();
  const { account } = useAuth();
  const canToggleShared = account?.role === "root";
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

  const toggleEdit = (key: string) => {
    const nextKey = editingSkillId === key ? null : key;
    requestNavigation(() => setEditingSkillId(nextKey));
  };

  return (
    <div className="page-scroll">
      <PageHeader
        title="工具與技能"
        subtitle="AI 回答時能用的技能，以及系統內建的工具。"
        actions={(
          <button
            type="button"
            onClick={handleReloadAll}
            disabled={busy}
            title="重新掃描技能檔案並刷新清單"
            className="btn btn-ghost"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">sync</span>
            <span>{reloading ? "重新載入中…" : loading ? "載入中…" : "重新載入"}</span>
          </button>
        )}
      />

      <div className="page-body space-y-8">
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
          canEdit
          canToggle
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
          readOnlyNotice={canToggleShared ? SHARED_NOTICE_ROOT : SHARED_NOTICE}
          canEdit={false}
          canToggle={canToggleShared}
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
              readOnly={editingSkill.scope !== "project"}
              onClose={() => requestNavigation(() => setEditingSkillId(null))}
              onSaved={load}
            />
          </section>
        )}

        <section>
          <h2 className="section-title mb-4 flex items-center gap-2">
            <span aria-hidden="true" className="material-symbols-outlined text-base">settings</span>
            內建工具
            <span className="text-xs font-mono text-content-subtle">({tools.length})</span>
          </h2>

          {tools.length > 0 && <ToolTable tools={tools} />}
        </section>

        {skillTools.length > 0 && (
          <section>
            <h2 className="section-title mb-4 flex items-center gap-2">
              <span aria-hidden="true" className="material-symbols-outlined text-base">extension</span>
              技能工具
              <span className="text-xs font-mono text-content-subtle">({skillTools.length})</span>
            </h2>

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

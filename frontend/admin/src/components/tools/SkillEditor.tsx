import { useEffect, useState } from "react";
import { fetchSkillFiles, updateSkillFiles } from "../../api";
import { useUnsavedChanges } from "../../context/NavigationGuardContext";
import { useLocalStorageState } from "../../hooks/useLocalStorageState";
import StatusAlert from "../StatusAlert";
import {
  changedFiles,
  filesChanged,
  isLockedSkillFile,
  SKILL_EDITOR_TABS,
  type SkillEditorTab,
} from "./helpers";

interface SkillEditorProps {
  skillId: string;
  scope?: "shared" | "project";
  projectId?: string;
  /** 只能看不能改，例如共用技能（內容要更新系統才能改）。 */
  readOnly?: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export default function SkillEditor({
  skillId,
  scope,
  projectId,
  readOnly = false,
  onClose,
  onSaved,
}: SkillEditorProps) {
  const [files, setFiles] = useState<Record<string, string>>({});
  const [activeTab, setActiveTab] = useLocalStorageState<SkillEditorTab>(
    "admin.tools.skill_editor_tab",
    "skill.yaml",
    SKILL_EDITOR_TABS,
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // 檔案沒載入成功就不能編輯或儲存：儲存會整包覆寫，送出空白底稿等於清掉伺服器上的技能。
  const [loaded, setLoaded] = useState(false);
  const [originalFiles, setOriginalFiles] = useState<Record<string, string>>({});
  const dirty = loaded && filesChanged(files, originalFiles);

  useUnsavedChanges(
    `skill-editor:${scope ?? "shared"}:${projectId ?? ""}:${skillId}`,
    dirty,
    `技能 ${skillId}`,
    saving,
  );

  useEffect(() => {
    setLoading(true);
    setLoaded(false);
    setError("");
    fetchSkillFiles(skillId, { scope, project_id: projectId })
      .then((data) => {
        setFiles(data.files);
        setOriginalFiles(data.files);
        setLoaded(true);
      })
      .catch((e) => setError(`無法載入技能檔案，請關閉後再試一次。${String(e)}`))
      .finally(() => setLoading(false));
  }, [skillId, scope, projectId]);

  const tabLocked = readOnly || isLockedSkillFile(activeTab);

  const handleChange = (content: string) => {
    if (!loaded || tabLocked) return;
    const nextFiles = { ...files, [activeTab]: content };
    setFiles(nextFiles);
  };

  const handleSave = () => {
    if (!loaded || saving) return;
    setSaving(true);
    setError("");
    // 只送改過的檔案：Brain 收到 main.py 一律拒絕，整包送會連 skill.yaml 都存不了。
    updateSkillFiles(skillId, changedFiles(files, originalFiles), { scope, project_id: projectId })
      .then(() => {
        setOriginalFiles({ ...files });
        onSaved();
      })
      .catch((e) => setError(String(e)))
      .finally(() => setSaving(false));
  };

  return (
    <div className="bg-surface dark:bg-surface-sunken/60 border border-primary/10 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-border">
        <div className="flex items-center gap-3">
          <span aria-hidden="true" className="material-symbols-outlined text-primary">
            {readOnly ? "visibility" : "edit_note"}
          </span>
          <span className="font-bold text-sm">{readOnly ? "檢視" : "編輯"}：{skillId}</span>
          {dirty && (
            <span className="px-2 py-0.5 text-[0.625rem] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded uppercase">
              未儲存
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!readOnly && (
            <button
              onClick={handleSave}
              disabled={saving || !loaded || !dirty}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg text-xs font-bold transition-all disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-sm">save</span>
              {saving ? "儲存中..." : "儲存並重載"}
            </button>
          )}
          <button
            onClick={onClose}
            // 儲存送出後一定會寫進伺服器，這時跳「捨棄並離開」會誤導；等儲存結束再關。
            disabled={saving}
            className="flex items-center gap-1 px-3 py-1.5 border border-border text-content-muted hover:text-content hover:border-border-strong rounded-lg text-xs transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">close</span>
            {saving ? "儲存完才能關閉" : "關閉"}
          </button>
        </div>
      </div>

      {error && (
        <div className="px-5 pt-3">
          <StatusAlert type="error" message={error} />
        </div>
      )}

      <div className="flex border-b border-border">
        {SKILL_EDITOR_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-5 py-2.5 text-xs font-bold transition-colors ${
              activeTab === tab
                ? "text-primary border-b-2 border-primary bg-border/50 dark:bg-surface-overlay/30"
                : "text-content-subtle hover:text-content"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {loaded && tabLocked && (
        <p className="px-5 pt-3 text-xs text-content-muted">
          {readOnly
            ? "共用技能會套用到所有專案，內容要更新系統才能修改，這裡只能查看。"
            : "程式碼（main.py）不能在這裡修改，需要請工程人員在伺服器上更新。"}
        </p>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-content-subtle text-sm">載入檔案中...</div>
      ) : !loaded ? (
        <div className="flex items-center justify-center py-16 text-content-subtle text-sm">
          檔案沒有載入，無法編輯。
        </div>
      ) : (
        <textarea
          aria-label={`${skillId} ${activeTab} 內容`}
          value={files[activeTab] ?? ""}
          onChange={(e) => handleChange(e.target.value)}
          readOnly={tabLocked}
          spellCheck={false}
          className="w-full h-[25rem] p-5 bg-transparent text-content text-xs leading-5 font-mono resize-y outline-none border-none"
          style={{ tabSize: 2 }}
        />
      )}
    </div>
  );
}

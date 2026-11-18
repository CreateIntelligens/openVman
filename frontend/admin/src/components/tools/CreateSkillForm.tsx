import { useState } from "react";
import { createSkill } from "../../api";
import { useProject } from "../../context/ProjectContext";
import StatusAlert from "../StatusAlert";
import { isValidSkillId, nameToId } from "./helpers";

interface CreateSkillFormProps {
  onCreated: () => void;
}

// 共用技能要改 repo 再部署，後台只建立目前專案的技能。
export default function CreateSkillForm({ onCreated }: CreateSkillFormProps) {
  const { projectId } = useProject();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [idOverride, setIdOverride] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const trimmedName = name.trim();
  const trimmedDescription = description.trim();
  const derivedId = idOverride || nameToId(name);
  const idValid = isValidSkillId(derivedId);
  const canCreate = Boolean(idValid && trimmedName);
  // 中文名稱轉不出 ID、或轉出來以數字開頭時，直接請使用者自己填。
  const showIdInput = idOverride !== "" || Boolean(trimmedName && !idValid);

  const reset = () => {
    setName("");
    setIdOverride("");
    setDescription("");
    setError("");
  };

  const handleCreate = () => {
    if (!canCreate) return;
    setCreating(true);
    setError("");
    createSkill(
      derivedId,
      trimmedName,
      trimmedDescription,
      projectId,
    )
      .then(() => {
        reset();
        setOpen(false);
        onCreated();
      })
      .catch((e) => setError(String(e)))
      .finally(() => setCreating(false));
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 px-4 py-2.5 border-2 border-dashed border-border-strong hover:border-primary/40 text-content-subtle hover:text-primary rounded-xl transition-colors w-full justify-center"
      >
        <span className="material-symbols-outlined text-lg">add</span>
        <span className="text-sm font-bold">建立技能</span>
      </button>
    );
  }

  return (
    <div className="bg-surface-sunken dark:bg-surface-sunken/40 border border-primary/10 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="card-title">新增技能</h4>
        <button
          onClick={() => {
            reset();
            setOpen(false);
          }}
          className="text-content-subtle hover:text-content "
        >
          <span className="material-symbols-outlined text-lg">close</span>
        </button>
      </div>

      {error && <StatusAlert type="error" message={error} />}

      <p className="text-xs text-content-muted">建立在目前專案（{projectId}），只有這個專案會用到。</p>

      <div>
        <label className="block text-[0.625rem] font-bold text-content-subtle uppercase tracking-widest mb-1">名稱</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="我的技能"
          className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-overlay/60 border border-border rounded-lg text-sm text-content placeholder-content-subtle outline-none focus:border-primary/40"
        />
        {name.trim() && idValid && (
          <p className="text-[0.625rem] text-content-subtle mt-1 font-mono">
            ID: {derivedId}
            {!idOverride && (
              <button onClick={() => setIdOverride(derivedId)} className="ml-2 text-primary hover:underline">
                編輯
              </button>
            )}
          </p>
        )}
      </div>

      {showIdInput && (
        <div>
          <label
            htmlFor="create-skill-id"
            className="block text-[0.625rem] font-bold text-content-subtle uppercase tracking-widest mb-1"
          >
            技能 ID
          </label>
          <input
            id="create-skill-id"
            value={idOverride}
            onChange={(e) => setIdOverride(e.target.value)}
            placeholder="my_skill"
            className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-overlay/60 border border-border rounded-lg text-sm text-content placeholder-content-subtle outline-none focus:border-primary/40"
          />
          {!idValid && (
            <p className="text-xs text-content-muted mt-1">
              技能 ID 只能用英文字母、數字與底線，而且不能以數字開頭，例如 my_skill。
            </p>
          )}
        </div>
      )}

      <div>
        <label className="block text-[0.625rem] font-bold text-content-subtle uppercase tracking-widest mb-1">說明</label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="選填說明..."
          className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-overlay/60 border border-border rounded-lg text-sm text-content placeholder-content-subtle outline-none focus:border-primary/40"
        />
      </div>

      <button
        onClick={handleCreate}
        disabled={creating || !canCreate}
        className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg text-sm font-bold transition-all disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-sm">add</span>
        {creating ? "建立中..." : "建立"}
      </button>
    </div>
  );
}

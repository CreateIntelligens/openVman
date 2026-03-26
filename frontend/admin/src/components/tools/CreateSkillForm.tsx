import { useState } from "react";
import { createSkill } from "../../api";
import StatusAlert from "../StatusAlert";
import { nameToId } from "./helpers";

interface CreateSkillFormProps {
  onCreated: () => void;
}

export default function CreateSkillForm({ onCreated }: CreateSkillFormProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [idOverride, setIdOverride] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const trimmedName = name.trim();
  const trimmedDescription = description.trim();
  const derivedId = idOverride || nameToId(name);
  const canCreate = Boolean(derivedId && trimmedName);

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
    createSkill(derivedId, trimmedName, trimmedDescription)
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
        className="flex items-center gap-2 px-4 py-2.5 border-2 border-dashed border-slate-700 hover:border-primary/40 text-slate-500 hover:text-primary rounded-xl transition-colors w-full justify-center"
      >
        <span className="material-symbols-outlined text-lg">add</span>
        <span className="text-sm font-bold">建立技能</span>
      </button>
    );
  }

  return (
    <div className="bg-slate-900/40 border border-primary/10 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-bold text-slate-200">新增技能</h4>
        <button
          onClick={() => {
            reset();
            setOpen(false);
          }}
          className="text-slate-500 hover:text-white"
        >
          <span className="material-symbols-outlined text-lg">close</span>
        </button>
      </div>

      {error && <StatusAlert type="error" message={error} />}

      <div>
        <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">名稱</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="我的技能"
          className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-primary/40"
        />
        {name.trim() && (
          <p className="text-[10px] text-slate-500 mt-1 font-mono">
            ID: {derivedId}
            {!idOverride && (
              <button onClick={() => setIdOverride(derivedId)} className="ml-2 text-primary hover:underline">
                編輯
              </button>
            )}
          </p>
        )}
      </div>

      {idOverride !== "" && (
        <div>
          <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">技能 ID</label>
          <input
            value={idOverride}
            onChange={(e) => setIdOverride(e.target.value)}
            placeholder="my_skill"
            className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-primary/40"
          />
        </div>
      )}

      <div>
        <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">說明</label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="選填說明..."
          className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-primary/40"
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

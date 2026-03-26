import { useEffect, useState } from "react";
import { fetchSkillFiles, updateSkillFiles } from "../../api";
import StatusAlert from "../StatusAlert";
import { filesChanged, SKILL_EDITOR_TABS, type SkillEditorTab } from "./helpers";

interface SkillEditorProps {
  skillId: string;
  onClose: () => void;
  onSaved: () => void;
}

export default function SkillEditor({ skillId, onClose, onSaved }: SkillEditorProps) {
  const [files, setFiles] = useState<Record<string, string>>({});
  const [activeTab, setActiveTab] = useState<SkillEditorTab>("skill.yaml");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [originalFiles, setOriginalFiles] = useState<Record<string, string>>({});

  useEffect(() => {
    setLoading(true);
    setError("");
    fetchSkillFiles(skillId)
      .then((data) => {
        setFiles(data.files);
        setOriginalFiles(data.files);
        setDirty(false);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [skillId]);

  const handleChange = (content: string) => {
    const nextFiles = { ...files, [activeTab]: content };
    setFiles(nextFiles);
    setDirty(filesChanged(nextFiles, originalFiles));
  };

  const handleSave = () => {
    setSaving(true);
    setError("");
    updateSkillFiles(skillId, files)
      .then(() => {
        setOriginalFiles({ ...files });
        setDirty(false);
        onSaved();
      })
      .catch((e) => setError(String(e)))
      .finally(() => setSaving(false));
  };

  return (
    <div className="bg-slate-900/60 border border-primary/10 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary">edit_note</span>
          <span className="font-bold text-sm">編輯：{skillId}</span>
          {dirty && (
            <span className="px-2 py-0.5 text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded uppercase">
              未儲存
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg text-xs font-bold transition-all disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">save</span>
            {saving ? "儲存中..." : "儲存並重載"}
          </button>
          <button
            onClick={onClose}
            className="flex items-center gap-1 px-3 py-1.5 border border-slate-700 text-slate-400 hover:text-white hover:border-slate-600 rounded-lg text-xs transition-colors"
          >
            <span className="material-symbols-outlined text-sm">close</span>
            關閉
          </button>
        </div>
      </div>

      {error && (
        <div className="px-5 pt-3">
          <StatusAlert type="error" message={error} />
        </div>
      )}

      <div className="flex border-b border-slate-800">
        {SKILL_EDITOR_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-5 py-2.5 text-xs font-bold transition-colors ${
              activeTab === tab
                ? "text-primary border-b-2 border-primary bg-slate-800/30"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-500 text-sm">載入檔案中...</div>
      ) : (
        <textarea
          value={files[activeTab] ?? ""}
          onChange={(e) => handleChange(e.target.value)}
          spellCheck={false}
          className="w-full h-[400px] p-5 bg-transparent text-slate-200 text-xs leading-5 font-mono resize-y outline-none border-none"
          style={{ tabSize: 2 }}
        />
      )}
    </div>
  );
}

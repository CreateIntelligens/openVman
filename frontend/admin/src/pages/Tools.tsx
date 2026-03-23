import { useEffect, useState, useCallback } from "react";
import {
  fetchTools,
  toggleSkill,
  createSkill,
  fetchSkillFiles,
  updateSkillFiles,
  deleteSkill,
  reloadAllSkills,
  type ToolInfo,
  type SkillInfo,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import ConfirmModal from "../components/ConfirmModal";

const SKILL_EDITOR_TABS = ["skill.yaml", "main.py"] as const;

type SkillEditorTab = (typeof SKILL_EDITOR_TABS)[number];

function filesChanged(currentFiles: Record<string, string>, originalFiles: Record<string, string>): boolean {
  return Object.keys(originalFiles).some((key) => currentFiles[key] !== originalFiles[key]);
}

function getSkillIdFromToolName(toolName: string): string {
  const colonIndex = toolName.indexOf(":");
  return colonIndex > 0 ? toolName.slice(0, colonIndex) : "";
}

// ---------------------------------------------------------------------------
// Skill Editor Panel
// ---------------------------------------------------------------------------

function SkillEditor({
  skillId,
  onClose,
  onSaved,
}: {
  skillId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
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
      {/* Editor Header */}
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

      {error && <div className="px-5 pt-3"><StatusAlert type="error" message={error} /></div>}

      {/* File Tabs */}
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

      {/* Editor Area */}
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

// ---------------------------------------------------------------------------
// Create Skill Form
// ---------------------------------------------------------------------------

function nameToId(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

function CreateSkillForm({ onCreated }: { onCreated: () => void }) {
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
        <button onClick={() => { reset(); setOpen(false); }} className="text-slate-500 hover:text-white">
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
              <button onClick={() => setIdOverride(derivedId)} className="ml-2 text-primary hover:underline">編輯</button>
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
              <div
                key={skill.id}
                className="bg-slate-900/40 border border-primary/10 rounded-xl p-5 transition-transform hover:scale-[1.02]"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                      <span className="material-symbols-outlined text-primary text-xl">extension</span>
                    </div>
                    <div>
                      <p className="font-bold text-sm">{skill.name}</p>
                      <p className="text-[10px] text-slate-500 font-mono">{skill.id} v{skill.version}</p>
                    </div>
                  </div>

                  {/* Toggle Switch */}
                  <button
                    onClick={() => handleToggle(skill)}
                    disabled={togglingIds.has(skill.id)}
                    title={skill.enabled ? "停用技能" : "啟用技能"}
                    className={`relative w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-50 ${
                      skill.enabled ? "bg-emerald-500" : "bg-slate-600"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-200 ${
                        skill.enabled ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>

                <p className="text-xs text-slate-400 mb-3 line-clamp-2">{skill.description}</p>

                {skill.warnings?.length > 0 && (
                  <div className="mb-3 space-y-1">
                    {skill.warnings.map((w, i) => (
                      <div key={i} className="flex items-start gap-1.5 px-2.5 py-1.5 bg-amber-500/10 border border-amber-500/20 rounded-lg">
                        <span className="material-symbols-outlined text-amber-400 text-[14px] mt-0.5 shrink-0">warning</span>
                        <span className="text-[11px] text-amber-300 leading-tight">{w}</span>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-[11px] text-slate-500">
                    <span className="material-symbols-outlined text-[14px]">handyman</span>
                    {skill.tools.length}個工具
                    <span className="text-slate-700 mx-1">|</span>
                    <span className="truncate font-mono max-w-[120px]" title={skill.tools.join(", ")}>
                      {skill.tools.join(", ")}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => setEditingSkillId(editingSkillId === skill.id ? null : skill.id)}
                      className="flex items-center gap-1 px-2 py-1 text-[11px] text-slate-400 hover:text-primary border border-slate-700 hover:border-primary/30 rounded-lg transition-colors"
                    >
                      <span className="material-symbols-outlined text-[14px]">edit</span>
                      編輯
                    </button>
                    <button
                      onClick={() => setDeleteTarget(skill)}
                      className="flex items-center gap-1 px-2 py-1 text-[11px] text-slate-400 hover:text-red-400 border border-slate-700 hover:border-red-500/30 rounded-lg transition-colors"
                      title="刪除"
                    >
                      <span className="material-symbols-outlined text-[14px]">delete</span>
                    </button>
                  </div>
                </div>
              </div>
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
            <div className="bg-slate-900/40 border border-primary/10 rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-widest text-slate-500 border-b border-slate-800">
                      <th className="px-6 py-3">名稱</th>
                      <th className="px-6 py-3">說明</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {tools.map((tool) => (
                      <tr key={tool.name} className="text-slate-300 hover:bg-slate-800/30 transition-colors">
                        <td className="px-6 py-3 font-mono text-xs whitespace-nowrap">{tool.name}</td>
                        <td className="px-6 py-3 text-xs text-slate-400 max-w-md truncate" title={tool.description}>
                          {tool.description}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
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

            <div className="bg-slate-900/40 border border-primary/10 rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-widest text-slate-500 border-b border-slate-800">
                      <th className="px-6 py-3">名稱</th>
                      <th className="px-6 py-3">說明</th>
                      <th className="px-6 py-3">技能</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {skillTools.map((tool) => {
                      const skillId = getSkillIdFromToolName(tool.name);
                      const skill = skills.find((s) => s.id === skillId);
                      return (
                        <tr key={tool.name} className="text-slate-300 hover:bg-slate-800/30 transition-colors">
                          <td className="px-6 py-3 font-mono text-xs whitespace-nowrap">{tool.name}</td>
                          <td className="px-6 py-3 text-xs text-slate-400 max-w-md truncate" title={tool.description}>
                            {tool.description}
                          </td>
                          <td className="px-6 py-3 whitespace-nowrap">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-primary/10 text-primary border border-primary/20">
                              <span className="material-symbols-outlined text-[12px]">extension</span>
                              {skill?.name ?? skillId}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
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

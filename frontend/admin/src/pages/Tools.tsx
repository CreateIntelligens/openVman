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
  const [activeTab, setActiveTab] = useState<"skill.yaml" | "main.py">("skill.yaml");
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
    const updated = { ...files, [activeTab]: content };
    setFiles(updated);
    const hasChanges = Object.keys(originalFiles).some(
      (key) => updated[key] !== originalFiles[key],
    );
    setDirty(hasChanges);
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

  const tabs: ("skill.yaml" | "main.py")[] = ["skill.yaml", "main.py"];

  return (
    <div className="bg-slate-900/60 border border-primary/10 rounded-xl overflow-hidden">
      {/* Editor Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary">edit_note</span>
          <span className="font-bold text-sm">Editing: {skillId}</span>
          {dirty && (
            <span className="px-2 py-0.5 text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded uppercase">
              Unsaved
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
            {saving ? "Saving..." : "Save & Reload"}
          </button>
          <button
            onClick={onClose}
            className="flex items-center gap-1 px-3 py-1.5 border border-slate-700 text-slate-400 hover:text-white hover:border-slate-600 rounded-lg text-xs transition-colors"
          >
            <span className="material-symbols-outlined text-sm">close</span>
            Close
          </button>
        </div>
      </div>

      {error && <div className="px-5 pt-3"><StatusAlert type="error" message={error} /></div>}

      {/* File Tabs */}
      <div className="flex border-b border-slate-800">
        {tabs.map((tab) => (
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
        <div className="flex items-center justify-center py-16 text-slate-500 text-sm">Loading files...</div>
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

function CreateSkillForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [skillId, setSkillId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const reset = () => {
    setSkillId("");
    setName("");
    setDescription("");
    setError("");
  };

  const handleCreate = () => {
    if (!skillId.trim() || !name.trim()) return;
    setCreating(true);
    setError("");
    createSkill(skillId.trim(), name.trim(), description.trim())
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
        <span className="text-sm font-bold">Create Skill</span>
      </button>
    );
  }

  return (
    <div className="bg-slate-900/40 border border-primary/10 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-bold text-slate-200">New Skill</h4>
        <button onClick={() => { reset(); setOpen(false); }} className="text-slate-500 hover:text-white">
          <span className="material-symbols-outlined text-lg">close</span>
        </button>
      </div>

      {error && <StatusAlert type="error" message={error} />}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Skill ID</label>
          <input
            value={skillId}
            onChange={(e) => setSkillId(e.target.value)}
            placeholder="my_skill"
            className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-primary/40"
          />
        </div>
        <div>
          <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Skill"
            className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-primary/40"
          />
        </div>
      </div>
      <div>
        <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Description</label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional description..."
          className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-primary/40"
        />
      </div>
      <button
        onClick={handleCreate}
        disabled={creating || !skillId.trim() || !name.trim()}
        className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg text-sm font-bold transition-all disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-sm">add</span>
        {creating ? "Creating..." : "Create"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function Tools() {
  const [tools, setTools] = useState<ToolInfo[]>([]);
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

  const getToolSource = useCallback(
    (name: string): { label: string; isSkill: boolean } => {
      const colonIdx = name.indexOf(":");
      if (colonIdx > 0) {
        const skillId = name.slice(0, colonIdx);
        const skill = skills.find((s) => s.id === skillId);
        return { label: skill?.name ?? skillId, isSkill: true };
      }
      return { label: "built-in", isSkill: false };
    },
    [skills],
  );

  return (
    <div className="page-scroll">
      {/* Header */}
      <header className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <div>
          <h2 className="text-2xl font-bold">Tools & Skills</h2>
          <p className="text-sm text-slate-400">
            Manage skill plugins and view registered tools
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleReloadAll}
            disabled={reloading}
            className="flex items-center gap-2 px-4 py-2 border border-slate-700 hover:border-primary/40 text-slate-300 hover:text-primary rounded-lg font-bold transition-all text-sm disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">sync</span>
            {reloading ? "Reloading..." : "Reload All Skills"}
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg font-bold transition-all shadow-lg shadow-primary/20 disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            <span>{loading ? "Loading..." : "Refresh"}</span>
          </button>
        </div>
      </header>

      <div className="p-8 space-y-8">
        {error && <StatusAlert type="error" message={error} />}

        {/* Skills Section */}
        <section>
          <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 px-1 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-base">extension</span>
            Skills
            <span className="text-xs font-mono text-slate-600">({skills.length})</span>
          </h3>

          {skills.length === 0 && !loading && !error && (
            <p className="text-sm text-slate-500 px-1 mb-4">No skills loaded.</p>
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
                    title={skill.enabled ? "Disable skill" : "Enable skill"}
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

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-[11px] text-slate-500">
                    <span className="material-symbols-outlined text-[14px]">handyman</span>
                    {skill.tools.length} tool{skill.tools.length !== 1 ? "s" : ""}
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
                      Edit
                    </button>
                    <button
                      onClick={() => setDeleteTarget(skill)}
                      className="flex items-center gap-1 px-2 py-1 text-[11px] text-slate-400 hover:text-red-400 border border-slate-700 hover:border-red-500/30 rounded-lg transition-colors"
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

        {/* Tools Section */}
        <section>
          <h3 className="text-sm font-bold uppercase tracking-widest text-slate-500 px-1 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-base">handyman</span>
            Tools
            <span className="text-xs font-mono text-slate-600">({tools.length})</span>
          </h3>

          {tools.length > 0 && (
            <div className="bg-slate-900/40 border border-primary/10 rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-widest text-slate-500 border-b border-slate-800">
                      <th className="px-6 py-3">Name</th>
                      <th className="px-6 py-3">Description</th>
                      <th className="px-6 py-3">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {tools.map((tool) => {
                      const source = getToolSource(tool.name);
                      return (
                        <tr key={tool.name} className="text-slate-300 hover:bg-slate-800/30 transition-colors">
                          <td className="px-6 py-3 font-mono text-xs whitespace-nowrap">{tool.name}</td>
                          <td className="px-6 py-3 text-xs text-slate-400 max-w-md truncate" title={tool.description}>
                            {tool.description}
                          </td>
                          <td className="px-6 py-3 whitespace-nowrap">
                            <span
                              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                                source.isSkill
                                  ? "bg-primary/10 text-primary border border-primary/20"
                                  : "bg-slate-800 text-slate-400 border border-slate-700"
                              }`}
                            >
                              <span className="material-symbols-outlined text-[12px]">
                                {source.isSkill ? "extension" : "settings"}
                              </span>
                              {source.label}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        open={!!deleteTarget}
        title="Delete Skill"
        message={deleteTarget ? `Are you sure you want to delete "${deleteTarget.name}" (${deleteTarget.id})?\n\nThis will permanently remove the skill directory and all its files.` : ""}
        confirmLabel="Delete"
        danger
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

import { useEffect, useState } from "react";
import {
  clonePersona,
  createPersona,
  deletePersona,
  fetchPersonas,
  fetchKnowledgeDocument,
  fetchKnowledgeDocuments,
  KnowledgeDocumentSummary,
  moveKnowledgeDocument,
  PersonaSummary,
  reindexKnowledge,
  saveKnowledgeDocument,
  uploadKnowledgeDocuments,
} from "../api";
import StatusAlert from "../components/StatusAlert";

type Status =
  | { type: "success" | "error"; message: string }
  | null;

const emptyDraft = {
  path: "",
  content: "",
};

const filters = [
  { key: "all", label: "All" },
  { key: "core", label: "Core" },
  { key: "personas", label: "Personas" },
  { key: "learnings", label: "Learnings" },
  { key: "logs", label: "Logs" },
  { key: "knowledge", label: "Knowledge" },
  { key: "other", label: "Other" },
] as const;

type FilterKey = (typeof filters)[number]["key"];

export default function Knowledge() {
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [knowledgeTargetPersonaId, setKnowledgeTargetPersonaId] = useState("global");
  const [newPersonaId, setNewPersonaId] = useState("");
  const [newPersonaLabel, setNewPersonaLabel] = useState("");
  const [cloneSourcePersonaId, setCloneSourcePersonaId] = useState("default");
  const [cloneTargetPersonaId, setCloneTargetPersonaId] = useState("");
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [loadedPath, setLoadedPath] = useState("");
  const [loadedContent, setLoadedContent] = useState("");
  const [status, setStatus] = useState<Status>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDocument, setLoadingDocument] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [creatingPersona, setCreatingPersona] = useState(false);
  const [cloningPersona, setCloningPersona] = useState(false);
  const [deletingPersonaId, setDeletingPersonaId] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");

  const hasUnsavedChanges =
    draftPath !== loadedPath || draftContent !== loadedContent;
  const filteredDocuments = documents.filter((document) =>
    matchDocumentFilter(document, activeFilter),
  );
  const groupedDocuments = groupDocuments(filteredDocuments);
  const quickAccessDocuments = getQuickAccessDocuments(documents);
  const personaKnowledgeTargetDir = getPersonaKnowledgeTargetDir(knowledgeTargetPersonaId);

  const loadPersonas = async () => {
    const response = await fetchPersonas();
    setPersonas(response.personas);
    setKnowledgeTargetPersonaId((current) =>
      resolveKnowledgeTargetPersonaId(current, response.personas),
    );
  };

  const loadDocuments = async (preferredPath?: string) => {
    setLoadingList(true);
    try {
      const response = await fetchKnowledgeDocuments();
      setDocuments(response.documents);
      const nextPath = getPreferredDocumentPath(
        response.documents,
        preferredPath,
        selectedPath,
      );

      if (nextPath) {
        await openDocument(nextPath, response.documents);
      } else {
        resetDraft(emptyDraft.path, emptyDraft.content);
      }
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setLoadingList(false);
    }
  };

  const openDocument = async (
    path: string,
    currentDocuments = documents,
  ) => {
    setLoadingDocument(true);
    setStatus(null);

    try {
      const response = await fetchKnowledgeDocument(path);
      setSelectedPath(response.path);
      setDraftPath(response.path);
      setDraftContent(response.content);
      setLoadedPath(response.path);
      setLoadedContent(response.content);
      if (!currentDocuments.some((document) => document.path === response.path)) {
        setDocuments((prev) => [...prev, toDocumentSummary(response)]);
      }
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setLoadingDocument(false);
    }
  };

  const resetDraft = (path: string, content: string) => {
    setSelectedPath("");
    setDraftPath(path);
    setDraftContent(content);
    setLoadedPath("");
    setLoadedContent("");
  };

  const createDocument = () => {
    resetDraft(getSuggestedDocumentPath(knowledgeTargetPersonaId), "# 新文件\n\n");
    setStatus(null);
  };

  const createPersonaKnowledgeDocument = (personaId: string) => {
    setKnowledgeTargetPersonaId(personaId);
    resetDraft(getSuggestedDocumentPath(personaId), "# Persona 知識文件\n\n");
    setStatus(null);
  };

  const saveDocument = async () => {
    if (!draftPath.trim()) {
      setStatus({ type: "error", message: "請先輸入檔案路徑，例如 `糖尿病/糖尿病.md`。" });
      return;
    }

    setSaving(true);
    setStatus(null);

    try {
      const nextPath = draftPath.trim();
      if (selectedPath && selectedPath !== nextPath) {
        await moveKnowledgeDocument(selectedPath, nextPath);
      }

      const response = await saveKnowledgeDocument(nextPath, draftContent);
      const statusMessage = buildSaveStatusMessage(selectedPath, nextPath, response.document.path);
      setSelectedPath(response.document.path);
      setStatus({ type: "success", message: statusMessage });
      setLoadedPath(response.document.path);
      setLoadedContent(draftContent);
      await loadDocuments(response.document.path);
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setSaving(false);
    }
  };

  const syncDocuments = async () => {
    setSyncing(true);
    setStatus(null);

    try {
      const response = await reindexKnowledge();
      setStatus({
        type: "success",
        message: `已重建 knowledge，文件 ${response.document_count} 份，chunk ${response.chunk_count} 筆。`,
      });
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setSyncing(false);
    }
  };

  const uploadFiles = async () => {
    if (!selectedFiles.length) {
      setStatus({ type: "error", message: "請先選擇要上傳的檔案。" });
      return;
    }

    setUploading(true);
    setStatus(null);

    try {
      const response = await uploadKnowledgeDocuments(selectedFiles, personaKnowledgeTargetDir);
      setStatus({
        type: "success",
        message: `已上傳 ${response.files.length} 個檔案到 ${personaKnowledgeTargetDir || "workspace root"}。`,
      });
      setSelectedFiles([]);
      await loadDocuments(response.files[0]?.path);
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setUploading(false);
    }
  };

  const createPersonaScaffold = async () => {
    if (!newPersonaId.trim()) {
      setStatus({ type: "error", message: "請先輸入 persona id，例如 `doctor`。" });
      return;
    }

    setCreatingPersona(true);
    setStatus(null);

    try {
      const response = await createPersona(newPersonaId.trim(), newPersonaLabel.trim());
      setStatus({
        type: "success",
        message: `已建立 persona ${response.persona.persona_id}，並生成 ${response.files.length} 份核心文件。`,
      });
      setNewPersonaId("");
      setNewPersonaLabel("");
      await loadPersonas();
      await loadDocuments(response.persona.path);
      setActiveFilter("personas");
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setCreatingPersona(false);
    }
  };

  const clonePersonaScaffold = async () => {
    if (!cloneTargetPersonaId.trim()) {
      setStatus({ type: "error", message: "請先輸入新的 target persona id。" });
      return;
    }

    setCloningPersona(true);
    setStatus(null);

    try {
      const response = await clonePersona(
        cloneSourcePersonaId,
        cloneTargetPersonaId.trim(),
      );
      setStatus({
        type: "success",
        message: `已從 ${response.source_persona_id} 複製 persona ${response.persona.persona_id}。`,
      });
      setCloneTargetPersonaId("");
      await loadPersonas();
      await loadDocuments(response.persona.path);
      setActiveFilter("personas");
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setCloningPersona(false);
    }
  };

  const deletePersonaScaffold = async (persona: PersonaSummary) => {
    if (persona.is_default) {
      return;
    }
    if (!window.confirm(`確定要刪除 persona \`${persona.persona_id}\` 嗎？`)) {
      return;
    }

    setDeletingPersonaId(persona.persona_id);
    setStatus(null);

    try {
      await deletePersona(persona.persona_id);
      setStatus({
        type: "success",
        message: `已刪除 persona ${persona.persona_id}。`,
      });
      await loadPersonas();
      await loadDocuments();
    } catch (error) {
      setStatus({ type: "error", message: String(error) });
    } finally {
      setDeletingPersonaId("");
    }
  };

  useEffect(() => {
    loadDocuments();
    loadPersonas().catch((error) => {
      setStatus({ type: "error", message: String(error) });
    });
  }, []);

  return (
    <>
      <header className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <div>
          <h2 className="text-2xl font-bold">Workspace Admin</h2>
          <p className="text-sm text-slate-400">
            管理整個 `workspace/`，編輯核心 markdown、上傳檔案並重建 knowledge。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => loadDocuments()}
            disabled={loadingList}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:border-primary/40 hover:text-white transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            {loadingList ? "Refreshing..." : "Refresh"}
          </button>
          <button
            onClick={syncDocuments}
            disabled={syncing}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white font-bold hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">data_object</span>
            {syncing ? "Syncing..." : "Reindex Knowledge"}
          </button>
        </div>
      </header>

      <div className="p-8 space-y-6">
        {status && <StatusAlert type={status.type} message={status.message} />}

        <section className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <div className="space-y-6">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
                  Personas
                </p>
                <h3 className="text-lg font-bold text-white">{personas.length} active personas</h3>
              </div>
              <div className="grid gap-3">
                {personas.map((persona) => (
                  <div
                    key={persona.persona_id}
                    className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-left text-sm text-slate-300"
                  >
                    <button
                      onClick={() => openDocument(persona.path)}
                      className="w-full text-left hover:text-white transition-colors"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-semibold text-white">{persona.persona_id}</span>
                        {persona.is_default && (
                          <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.2em] text-amber-300">
                            default
                          </span>
                        )}
                      </div>
                      <p className="mt-2 text-xs text-slate-500">{persona.path}</p>
                      <p className="mt-3 line-clamp-2 text-sm text-slate-400">{persona.preview}</p>
                    </button>
                    {!persona.is_default && (
                      <div className="mt-4 flex justify-end gap-2">
                        <button
                          onClick={() => createPersonaKnowledgeDocument(persona.persona_id)}
                          className="rounded-lg border border-primary/20 bg-primary/10 px-3 py-2 text-xs font-semibold text-primary hover:bg-primary/15"
                        >
                          New Knowledge Doc
                        </button>
                        <button
                          onClick={() => void deletePersonaScaffold(persona)}
                          disabled={deletingPersonaId === persona.persona_id}
                          className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/15 disabled:opacity-50"
                        >
                          {deletingPersonaId === persona.persona_id ? "Deleting..." : "Delete Persona"}
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className="rounded-2xl border border-dashed border-slate-700 p-4 space-y-3">
                <div className="grid gap-3">
                  <input
                    value={newPersonaId}
                    onChange={(event) => setNewPersonaId(event.target.value)}
                    placeholder="persona id，例如 doctor"
                    className="w-full rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
                  />
                  <input
                    value={newPersonaLabel}
                    onChange={(event) => setNewPersonaLabel(event.target.value)}
                    placeholder="顯示名稱，例如 醫師助理"
                    className="w-full rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
                  />
                </div>
                <p className="text-xs leading-6 text-slate-500">
                  建立後會自動生成 `SOUL.md / AGENTS.md / TOOLS.md / MEMORY.md`，並直接出現在目前的 Workspace 編輯器。
                </p>
                <button
                  onClick={createPersonaScaffold}
                  disabled={creatingPersona}
                  className="w-full rounded-lg bg-slate-800 px-4 py-3 font-medium text-white hover:bg-slate-700 transition-colors disabled:opacity-50"
                >
                  {creatingPersona ? "Creating Persona..." : "Create Persona"}
                </button>
              </div>
              <div className="rounded-2xl border border-dashed border-slate-700 p-4 space-y-3">
                <div className="grid gap-3">
                  <select
                    value={cloneSourcePersonaId}
                    onChange={(event) => setCloneSourcePersonaId(event.target.value)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm text-white focus:border-primary/50 focus:outline-none"
                  >
                    {personas.map((persona) => (
                      <option key={persona.persona_id} value={persona.persona_id}>
                        Clone from {persona.persona_id}
                      </option>
                    ))}
                  </select>
                  <input
                    value={cloneTargetPersonaId}
                    onChange={(event) => setCloneTargetPersonaId(event.target.value)}
                    placeholder="新的 target persona id，例如 doctor_v2"
                    className="w-full rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
                  />
                </div>
                <p className="text-xs leading-6 text-slate-500">
                  會直接複製來源 persona 的四份 core docs；建立後你可以再進編輯器微調內容。
                </p>
                <button
                  onClick={clonePersonaScaffold}
                  disabled={cloningPersona || !personas.length}
                  className="w-full rounded-lg bg-slate-800 px-4 py-3 font-medium text-white hover:bg-slate-700 transition-colors disabled:opacity-50"
                >
                  {cloningPersona ? "Cloning Persona..." : "Clone Persona"}
                </button>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
                    Documents
                  </p>
                  <h3 className="text-lg font-bold text-white">{documents.length} files</h3>
                </div>
                <button
                  onClick={createDocument}
                  className="flex items-center gap-2 rounded-lg border border-primary/30 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/10 transition-colors"
                >
                  <span className="material-symbols-outlined text-sm">note_add</span>
                  New
                </button>
              </div>

              <div className="mb-4 space-y-2 rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <label className="text-xs font-bold uppercase tracking-[0.24em] text-slate-500">
                  Knowledge Target
                </label>
                <select
                  value={knowledgeTargetPersonaId}
                  onChange={(event) => setKnowledgeTargetPersonaId(event.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm text-white focus:border-primary/50 focus:outline-none"
                >
                  <option value="global">Global Workspace</option>
                  {personas
                    .filter((persona) => !persona.is_default)
                    .map((persona) => (
                      <option key={persona.persona_id} value={persona.persona_id}>
                        Persona Knowledge: {persona.persona_id}
                      </option>
                    ))}
                </select>
                <p className="text-xs text-slate-500">
                  `New` 會依這個目標自動建立建議路徑，`Upload` 也會上傳到相同目錄。
                </p>
              </div>

              <div className="mb-4 flex flex-wrap gap-2">
                {filters.map((filter) => (
                  <button
                    key={filter.key}
                    onClick={() => setActiveFilter(filter.key)}
                    className={`rounded-full px-3 py-2 text-xs font-semibold transition-colors ${
                      activeFilter === filter.key
                        ? "bg-primary text-white"
                        : "border border-slate-800 bg-slate-950/40 text-slate-400"
                    }`}
                  >
                    {filter.label}
                  </button>
                ))}
              </div>

              <div className="mb-4 grid gap-2">
                {quickAccessDocuments.map((document) => (
                  <button
                    key={document.path}
                    onClick={() => openDocument(document.path)}
                    className="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3 text-left text-sm text-slate-300 hover:border-primary/30 hover:bg-primary/5 transition-colors"
                  >
                    Quick Open: {document.path}
                  </button>
                ))}
              </div>

              <div className="space-y-5 max-h-[520px] overflow-y-auto pr-1">
                {groupedDocuments.map(([section, sectionDocuments]) => (
                  <div key={section} className="space-y-3">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-bold uppercase tracking-[0.28em] text-slate-500">
                        {section}
                      </p>
                      <span className="text-xs text-slate-500">{sectionDocuments.length}</span>
                    </div>
                    {sectionDocuments.map((document) => {
                      const isActive = document.path === selectedPath;
                      return (
                        <button
                          key={document.path}
                          onClick={() => openDocument(document.path)}
                          className={`w-full rounded-xl border p-4 text-left transition-colors ${
                            isActive
                              ? "border-primary/40 bg-primary/10"
                              : "border-slate-800 bg-slate-950/40 hover:border-slate-700"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <h4 className="font-semibold text-white truncate">{document.title}</h4>
                            <div className="flex items-center gap-2">
                              {document.is_core && (
                                <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.2em] text-amber-300">
                                  core
                                </span>
                              )}
                              {!document.is_indexable && !document.is_core && (
                                <span className="rounded-full border border-slate-700 bg-slate-800/80 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">
                                  no index
                                </span>
                              )}
                              <span className="text-[10px] font-bold uppercase tracking-[0.24em] text-slate-500">
                                {document.extension.replace(".", "")}
                              </span>
                            </div>
                          </div>
                          <p className="mt-2 text-xs text-slate-500 truncate">
                            {document.category || "root"} / {document.path}
                          </p>
                          <p className="mt-3 text-sm text-slate-400 line-clamp-3">{document.preview || "No preview"}</p>
                          <div className="mt-3 flex items-center justify-between text-[11px] text-slate-500">
                            <span>{formatFileSize(document.size)}</span>
                            <span>{formatTimestamp(document.updated_at)}</span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ))}

                {!filteredDocuments.length && !loadingList && (
                  <div className="rounded-xl border border-dashed border-slate-800 p-6 text-sm text-slate-500">
                    目前這個 filter 下沒有文件。可以切換分類，或直接建立新 markdown。
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
                  Upload
                </p>
                <h3 className="text-lg font-bold text-white">Drop source files into workspace</h3>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3 text-xs text-slate-400">
                Upload target: {personaKnowledgeTargetDir || "workspace root"}
              </div>
              <input
                type="file"
                accept=".md,.txt,.csv"
                multiple
                onChange={(event) => setSelectedFiles(Array.from(event.target.files ?? []))}
                className="block w-full text-sm text-slate-400 file:mr-4 file:rounded-lg file:border-0 file:bg-primary/15 file:px-4 file:py-2 file:font-semibold file:text-primary hover:file:bg-primary/25"
              />
              <div className="text-xs text-slate-500">
                支援 UTF-8 編碼的 `.md`、`.txt`、`.csv`。上傳後仍可在右側直接修改內容。
              </div>
              <button
                onClick={uploadFiles}
                disabled={uploading || !selectedFiles.length}
                className="w-full rounded-lg bg-slate-800 px-4 py-3 font-medium text-white hover:bg-slate-700 transition-colors disabled:opacity-50"
              >
                {uploading ? "Uploading..." : `Upload ${selectedFiles.length || ""}`.trim()}
              </button>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6 space-y-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.3em] text-slate-500">
                  Editor
                </p>
                <h3 className="text-lg font-bold text-white">
                  {draftPath || "Create a new workspace document"}
                </h3>
              </div>
              <div className="text-xs text-slate-500">
                {loadingDocument ? "Loading document..." : `${draftContent.length.toLocaleString()} chars`}
              </div>
            </div>

            <div className="space-y-2">
              <label htmlFor="knowledge-path" className="text-sm font-medium text-slate-300">
                Relative Path
              </label>
              <input
                id="knowledge-path"
                value={draftPath}
                onChange={(event) => setDraftPath(event.target.value)}
                placeholder="例如：糖尿病/糖尿病.md"
                className="w-full rounded-xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-sm text-white placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
              />
              <p className="text-xs text-slate-500">
                修改這個路徑再按 `Save Document`，會直接在 workspace 內搬移或重新分類檔案。
              </p>
            </div>

            <div className="space-y-2">
              <label htmlFor="knowledge-content" className="text-sm font-medium text-slate-300">
                Content
              </label>
              <textarea
                id="knowledge-content"
                value={draftContent}
                onChange={(event) => setDraftContent(event.target.value)}
                rows={24}
                className="min-h-[560px] w-full rounded-2xl border border-slate-700 bg-slate-950/60 p-4 text-sm leading-7 text-slate-200 placeholder:text-slate-500 focus:border-primary/50 focus:outline-none"
                placeholder="# 衛教主題\n\nQ1：...\nA：..."
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-5">
              <div className="text-xs text-slate-500">
                {hasUnsavedChanges ? "有未儲存變更" : "內容已同步到編輯器"}
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={createDocument}
                  className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:text-white hover:border-slate-600 transition-colors"
                >
                  Clear
                </button>
                <button
                  onClick={saveDocument}
                  disabled={saving || !draftPath.trim()}
                  className="rounded-lg bg-primary px-5 py-2 text-sm font-bold text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Save Document"}
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function matchDocumentFilter(document: KnowledgeDocumentSummary, filter: FilterKey) {
  switch (filter) {
    case "all":
      return true;
    case "core":
      return document.is_core;
    case "personas":
      return document.path.startsWith("personas/");
    case "learnings":
      return document.path.startsWith(".learnings/");
    case "logs":
      return document.path.startsWith("memory/");
    case "knowledge":
      return document.is_indexable && !document.is_core;
    case "other":
      return (
        !document.is_core &&
        !document.path.startsWith(".learnings/") &&
        !document.path.startsWith("memory/") &&
        !document.is_indexable
      );
  }
}

function groupDocuments(documents: KnowledgeDocumentSummary[]) {
  const groups = new Map<string, KnowledgeDocumentSummary[]>();

  for (const document of documents) {
    const section = getDocumentSection(document);
    const list = groups.get(section) ?? [];
    list.push(document);
    groups.set(section, list);
  }

  return Array.from(groups.entries());
}

function getDocumentSection(document: KnowledgeDocumentSummary) {
  const personaSection = getPersonaDocumentSection(document.path);
  if (personaSection) {
    return personaSection;
  }
  if (document.is_core) {
    return "Core";
  }
  if (document.path.startsWith(".learnings/")) {
    return "Learnings";
  }
  if (document.path.startsWith("memory/")) {
    return "Daily Logs";
  }
  if (document.path.startsWith("hospital_education/")) {
    return "Hospital Knowledge";
  }
  if (document.is_indexable) {
    return "Knowledge";
  }
  return "Other Workspace";
}


function getQuickAccessDocuments(documents: KnowledgeDocumentSummary[]) {
  return documents.filter(
    (document) =>
      document.path === ".learnings/LEARNINGS.md" ||
      document.path === ".learnings/ERRORS.md",
  );
}

function resolveKnowledgeTargetPersonaId(
  currentPersonaId: string,
  personas: PersonaSummary[],
) {
  if (currentPersonaId === "global") {
    return currentPersonaId;
  }

  return personas.some((persona) => persona.persona_id === currentPersonaId)
    ? currentPersonaId
    : "global";
}

function getPreferredDocumentPath(
  documents: KnowledgeDocumentSummary[],
  preferredPath: string | undefined,
  selectedPath: string,
) {
  if (preferredPath) {
    return preferredPath;
  }
  if (documents.some((document) => document.path === selectedPath)) {
    return selectedPath;
  }
  return documents[0]?.path ?? "";
}

function toDocumentSummary(document: KnowledgeDocumentSummary & { content?: string }): KnowledgeDocumentSummary {
  const { content: _, ...summary } = document;
  return summary;
}

function buildSaveStatusMessage(
  selectedPath: string,
  requestedPath: string,
  savedPath: string,
) {
  if (selectedPath && selectedPath !== requestedPath) {
    return `已移動並儲存到 ${savedPath}`;
  }
  return `已儲存 ${savedPath}`;
}

function getPersonaKnowledgeTargetDir(personaId: string) {
  if (!personaId || personaId === "global") {
    return "";
  }
  return `personas/${personaId}/knowledge`;
}

function getSuggestedDocumentPath(personaId: string) {
  const targetDir = getPersonaKnowledgeTargetDir(personaId);
  if (!targetDir) {
    return "new-document.md";
  }
  return `${targetDir}/new-document.md`;
}

function getPersonaDocumentSection(path: string) {
  const parts = path.split("/");
  if (parts.length < 3 || parts[0] !== "personas") {
    return "";
  }
  const personaId = parts[1];
  if (parts[2] === "knowledge") {
    return `Persona Knowledge · ${personaId}`;
  }
  return `Persona Core · ${personaId}`;
}

import { useEffect, useState } from "react";
import {
       clonePersona,
       createPersona,
       deletePersona,
       fetchPersonas,
       fetchKnowledgeDocument,
       PersonaSummary,
       saveKnowledgeDocument,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import ConfirmModal from "../components/ConfirmModal";
import MarkdownPreview from "../components/MarkdownPreview";
import { useProject } from "../context/ProjectContext";

type EditorMode = "edit" | "preview" | "split";
type Status = { type: "success" | "error"; message: string } | null;

export default function Personas() {
       const { projectId } = useProject();
       const [personas, setPersonas] = useState<PersonaSummary[]>([]);
       const [newPersonaId, setNewPersonaId] = useState("");
       const [newPersonaLabel, setNewPersonaLabel] = useState("");
       const [templateSourceId, setTemplateSourceId] = useState("");

       const [selectedPersona, setSelectedPersona] = useState<PersonaSummary | null>(null);

       // Document Editor State
       const [selectedPath, setSelectedPath] = useState("");
       const [draftContent, setDraftContent] = useState("");
       const [loadedContent, setLoadedContent] = useState("");

       const [status, setStatus] = useState<Status>(null);
       const [loadingList, setLoadingList] = useState(false);
       const [loadingDocument, setLoadingDocument] = useState(false);
       const [saving, setSaving] = useState(false);
       const [creatingPersona, setCreatingPersona] = useState(false);
       const [cloningPersona, setCloningPersona] = useState(false);
       const [deletingPersonaId, setDeletingPersonaId] = useState("");

       const [editorMode, setEditorMode] = useState<EditorMode>("edit");
       const [deletePersonaTarget, setDeletePersonaTarget] = useState<PersonaSummary | null>(null);

       const hasUnsavedChanges = draftContent !== loadedContent;

       const loadPersonas = async (preferredId?: string) => {
              setLoadingList(true);
              try {
                     const response = await fetchPersonas();
                     setPersonas(response.personas);

                     let nextPersona = response.personas.find((p) => p.persona_id === preferredId);
                     if (!nextPersona && response.personas.length > 0) {
                            nextPersona = response.personas[0];
                     }

                     if (nextPersona) {
                            setSelectedPersona(nextPersona);
                            if (nextPersona.path) {
                                   await openDocument(nextPersona.path);
                            }
                     } else {
                            setSelectedPersona(null);
                            setDraftContent("");
                            setLoadedContent("");
                     }
              } catch (error) {
                     setStatus({ type: "error", message: String(error) });
              } finally {
                     setLoadingList(false);
              }
       };

       const openDocument = async (path: string) => {
              setLoadingDocument(true);
              setStatus(null);
              try {
                     const response = await fetchKnowledgeDocument(path);
                     setSelectedPath(response.path);
                     setDraftContent(response.content);
                     setLoadedContent(response.content);
              } catch (error) {
                     setStatus({ type: "error", message: String(error) });
              } finally {
                     setLoadingDocument(false);
              }
       };

       const saveDocument = async () => {
              if (!selectedPath) return;

              setSaving(true);
              setStatus(null);

              try {
                     await saveKnowledgeDocument(selectedPath, draftContent);
                     setStatus({ type: "success", message: `已儲存 ${selectedPath}` });
                     setLoadedContent(draftContent);
                     await loadPersonas(selectedPersona?.persona_id);
              } catch (error) {
                     setStatus({ type: "error", message: String(error) });
              } finally {
                     setSaving(false);
              }
       };

       const handleCreateOrClone = async () => {
              if (!newPersonaId.trim()) {
                     setStatus({ type: "error", message: "請輸入要建立的 Persona ID (例如 `doctor`)。" });
                     return;
              }

              setStatus(null);

              // If a template is selected (not empty), clone that existing persona
              if (templateSourceId) {
                     setCloningPersona(true);
                     try {
                            const response = await clonePersona(templateSourceId, newPersonaId.trim());
                            setStatus({
                                   type: "success",
                                   message: `已從 ${response.source_persona_id} 複製 persona ${response.persona.persona_id}。`,
                            });
                            setNewPersonaId("");
                            setNewPersonaLabel("");
                            setTemplateSourceId("");
                            await loadPersonas(response.persona.persona_id);
                     } catch (error) {
                            setStatus({ type: "error", message: String(error) });
                     } finally {
                            setCloningPersona(false);
                     }
              } else {
                     // Otherwise, create from the default blank template
                     setCreatingPersona(true);
                     try {
                            const response = await createPersona(newPersonaId.trim(), newPersonaLabel.trim());
                            setStatus({
                                   type: "success",
                                   message: `已建立 persona ${response.persona.persona_id}，並生成 核心文件。`,
                            });
                            setNewPersonaId("");
                            setNewPersonaLabel("");
                            await loadPersonas(response.persona.persona_id);
                     } catch (error) {
                            setStatus({ type: "error", message: String(error) });
                     } finally {
                            setCreatingPersona(false);
                     }
              }
       };

       const confirmDeletePersona = async () => {
              const persona = deletePersonaTarget;
              if (!persona) return;
              setDeletePersonaTarget(null);
              setDeletingPersonaId(persona.persona_id);
              setStatus(null);

              try {
                     await deletePersona(persona.persona_id);
                     setStatus({
                            type: "success",
                            message: `已刪除 persona ${persona.persona_id}。`,
                     });
                     await loadPersonas();
              } catch (error) {
                     setStatus({ type: "error", message: String(error) });
              } finally {
                     setDeletingPersonaId("");
              }
       };

       useEffect(() => {
              loadPersonas();
              // eslint-disable-next-line react-hooks/exhaustive-deps
       }, [projectId]);

       // Default persona uses workspace-root paths; others use personas/<id>/
       const docPrefix = selectedPersona?.is_default ? "" : `personas/${selectedPersona?.persona_id}/`;
       const coreDocs = selectedPersona
              ? [
                     { path: selectedPersona.path, label: "SOUL.md", icon: "psychology" },
                     { path: `${docPrefix}AGENTS.md`, label: "AGENTS.md", icon: "group_work" },
                     { path: `${docPrefix}TOOLS.md`, label: "TOOLS.md", icon: "build" },
                     { path: `${docPrefix}MEMORY.md`, label: "MEMORY.md", icon: "memory" },
              ]
              : [];

       return (
              <div className="flex h-full w-full overflow-hidden bg-background">
                     {/* Contextual Sidebar */}
                     <aside className="w-[300px] lg:w-[320px] flex-shrink-0 border-r border-slate-800/60 bg-slate-950/30 flex flex-col hidden md:flex z-10">
                            {/* Sidebar Header */}
                            <div className="px-5 py-5 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/20">
                                   <div className="flex items-center gap-2.5">
                                          <div className="w-6 h-6 rounded flex items-center justify-center bg-slate-800 text-slate-300">
                                                 <span className="material-symbols-outlined text-[14px]">groups_2</span>
                                          </div>
                                          <h2 className="text-[13px] font-semibold tracking-wide text-slate-200">角色管理</h2>
                                   </div>
                                   <button
                                          onClick={() => loadPersonas(selectedPersona?.persona_id)}
                                          disabled={loadingList}
                                          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors disabled:opacity-50"
                                          title="重新整理"
                                   >
                                          <span className={`material-symbols-outlined text-[16px] ${loadingList ? "animate-spin text-slate-200" : ""}`}>
                                                 refresh
                                          </span>
                                   </button>
                            </div>

                            <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none no-scrollbar">
                                   {/* Persona List */}
                                   <div>
                                          <div className="flex items-center justify-between mb-3 px-1 text-[11px] font-medium text-slate-500 uppercase tracking-wider">
                                                 <span>角色庫（{personas.length}）</span>
                                          </div>
                                          <div className="grid gap-1">
                                                 {personas.map((persona) => (
                                                        <div
                                                               key={persona.persona_id}
                                                               className={`rounded-md p-2.5 text-left transition-colors cursor-pointer border ${selectedPersona?.persona_id === persona.persona_id
                                                                      ? "bg-slate-800/60 border-slate-700 shadow-sm"
                                                                      : "bg-transparent border-transparent hover:bg-slate-800/30"
                                                                      }`}
                                                               onClick={() => {
                                                                      setSelectedPersona(persona);
                                                                      openDocument(persona.path);
                                                               }}
                                                        >
                                                               <div className="flex items-center justify-between gap-2">
                                                                      <span className={`font-semibold truncate text-sm ${selectedPersona?.persona_id === persona.persona_id ? "text-primary" : "text-slate-300"
                                                                             }`}>
                                                                             {persona.label || persona.persona_id}
                                                                      </span>
                                                                      <div className="flex items-center gap-1.5 shrink-0">
                                                                             {persona.is_default && (
                                                                                    <span className="rounded flex items-center bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest text-amber-500">
                                                                                           預設
                                                                                    </span>
                                                                             )}
                                                                      </div>
                                                               </div>

                                                               <div className="mt-1.5 flex items-center justify-between">
                                                                      <span className="text-[10px] font-mono text-slate-500 truncate">{persona.persona_id}</span>
                                                                      {selectedPersona?.persona_id === persona.persona_id && !persona.is_default && (
                                                                             <button
                                                                                    onClick={(e) => {
                                                                                           e.stopPropagation();
                                                                                           setDeletePersonaTarget(persona);
                                                                                    }}
                                                                                    disabled={deletingPersonaId === persona.persona_id}
                                                                                    className="flex items-center justify-center rounded bg-red-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-red-400 hover:bg-red-500 hover:text-white transition-colors disabled:opacity-50"
                                                                             >
                                                                                    {deletingPersonaId === persona.persona_id ? "..." : "DEL"}
                                                                             </button>
                                                                      )}
                                                               </div>
                                                        </div>
                                                 ))}
                                          </div>
                                   </div>

                                   <hr className="border-slate-800/60" />

                                   {/* Create / Clone Persona Form */}
                                   <div className="rounded-md border border-slate-800/60 bg-slate-900/20 p-4 space-y-4">
                                          <h3 className="text-[12px] font-semibold text-slate-300 flex items-center gap-1.5">新增角色</h3>
                                          <div className="space-y-3">
                                                 <input
                                                        value={newPersonaId}
                                                        onChange={(event) => setNewPersonaId(event.target.value)}
                                                        placeholder="ID（例如 support）"
                                                        className="w-full rounded-md border border-slate-700 bg-slate-900/50 px-3 py-2 text-[13px] text-slate-200 placeholder:text-slate-600 focus:border-slate-500 focus:outline-none transition-colors"
                                                        title="唯一角色 ID（用於資料夾路徑）"
                                                 />
                                                 <input
                                                        value={newPersonaLabel}
                                                        onChange={(event) => setNewPersonaLabel(event.target.value)}
                                                        placeholder="名稱（例如 Support Bot）"
                                                        className="w-full rounded-md border border-slate-700 bg-slate-900/50 px-3 py-2 text-[13px] text-slate-200 placeholder:text-slate-600 focus:border-slate-500 focus:outline-none transition-colors"
                                                        title="顯示名稱（僅套用於空白範本）"
                                                 />
                                                 <div className="relative">
                                                        <select
                                                               value={templateSourceId}
                                                               onChange={(event) => setTemplateSourceId(event.target.value)}
                                                               className="select-dark w-full text-[13px]"
                                                               title="選擇範本或現有角色複製設定"
                                                        >
                                                               <option value="">── 空白範本 ──</option>
                                                               {personas.map((persona) => (
                                                                      <option key={persona.persona_id} value={persona.persona_id}>
                                                                             複製自 {persona.persona_id}
                                                                      </option>
                                                               ))}
                                                        </select>
                                                        <span className="material-symbols-outlined text-[14px] text-slate-500 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none">expand_more</span>
                                                 </div>
                                          </div>
                                          <button
                                                 onClick={handleCreateOrClone}
                                                 disabled={creatingPersona || cloningPersona || !newPersonaId.trim()}
                                                 className="w-full rounded-md bg-primary px-3 py-2 text-[13px] font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
                                          >
                                                 {(creatingPersona || cloningPersona) ? "建立中..." : "建立角色"}
                                          </button>
                                   </div>
                            </div>
                     </aside>

                     {/* Main Editor Content */}
                     <main className="flex-1 flex flex-col min-w-0 bg-background relative overflow-hidden">
                            {status && (
                                   <div className="p-4 shrink-0 shadow-sm z-20 border-b border-slate-800/60">
                                          <StatusAlert type={status.type} message={status.message} />
                                   </div>
                            )}

                            {selectedPersona ? (
                                   <div className="flex-1 flex flex-col min-h-0 p-4 lg:p-8 z-10">
                                          <div className="flex flex-col gap-6 mb-6 shrink-0">
                                                 <div className="flex items-end justify-between">
                                                        <div className="flex items-center gap-4">
                                                               <div className="w-10 h-10 rounded border border-slate-700 bg-slate-900/50 flex items-center justify-center text-slate-300">
                                                                      <span className="material-symbols-outlined text-[20px]">psychology</span>
                                                               </div>
                                                               <div>
                                                                      <h3 className="text-[20px] font-semibold text-slate-200 leading-tight tracking-tight mb-0.5">
                                                                             {selectedPersona.label || selectedPersona.persona_id}
                                                                      </h3>
                                                                      <div className="flex items-center gap-2">
                                                                             <span className="text-[11px] font-mono text-slate-500">{selectedPath}</span>
                                                                      </div>
                                                               </div>
                                                        </div>
                                                        <div className="flex items-center gap-4 shrink-0">
                                                               <div className="flex rounded-md border border-slate-700 overflow-hidden bg-slate-900">
                                                                      {(["edit", "split", "preview"] as EditorMode[]).map((mode) => (
                                                                             <button
                                                                                    key={mode}
                                                                                    onClick={() => setEditorMode(mode)}
                                                                                    className={`px-3 py-1 text-[11px] font-medium transition-colors ${editorMode === mode
                                                                                           ? "bg-slate-700 text-white"
                                                                                           : "text-slate-400 hover:text-white hover:bg-slate-800"
                                                                                           }`}
                                                                             >
                                                                                    {mode.charAt(0).toUpperCase() + mode.slice(1)}
                                                                             </button>
                                                                      ))}
                                                               </div>
                                                        </div>
                                                 </div>

                                                 <div className="flex gap-2 overflow-x-auto no-scrollbar border-b border-slate-800/60 pb-3">
                                                        {coreDocs.map((doc) => (
                                                               <button
                                                                      key={doc.path}
                                                                      onClick={() => openDocument(doc.path)}
                                                                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors whitespace-nowrap border ${selectedPath === doc.path
                                                                             ? "bg-slate-800/60 border-slate-700 text-slate-200 shadow-sm"
                                                                             : "bg-transparent border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30"
                                                                             }`}
                                                               >
                                                                      <span className={`material-symbols-outlined text-[16px] ${selectedPath === doc.path ? "text-slate-200" : ""}`}>{doc.icon}</span>
                                                                      {doc.label}
                                                               </button>
                                                        ))}
                                                 </div>
                                          </div>

                                          <div className="flex-1 min-h-0 relative mb-5 rounded-xl border border-slate-800/50 bg-slate-950/30 overflow-hidden shadow-inner flex">
                                                 {loadingDocument && (
                                                        <div className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm z-10 flex items-center justify-center">
                                                               <div className="flex items-center gap-2 text-primary font-bold">
                                                                      <span className="material-symbols-outlined animate-spin text-[16px]">refresh</span>
                                                                      載入中...
                                                               </div>
                                                        </div>
                                                 )}
                                                 {editorMode === "edit" || editorMode === "split" ? (
                                                        <textarea
                                                               value={draftContent}
                                                               onChange={(event) => setDraftContent(event.target.value)}
                                                               className={`h-full w-full bg-transparent p-6 text-[13px] leading-relaxed text-slate-200 placeholder:text-slate-600 focus:outline-none font-mono resize-none ${editorMode === "split" ? "border-r border-slate-800/50" : ""
                                                                      }`}
                                                        />
                                                 ) : null}
                                                 {editorMode === "preview" || editorMode === "split" ? (
                                                        <div className="h-full w-full p-8 overflow-y-auto prose-container bg-slate-900/20">
                                                               <MarkdownPreview content={draftContent} />
                                                        </div>
                                                 ) : null}
                                          </div>

                                          <div className="flex items-center justify-between shrink-0 pt-2 px-1">
                                                 <div className="flex items-center gap-2 text-[11px] text-slate-500 font-medium">
                                                        <span className={`w-2 h-2 rounded-full transition-colors duration-300 ${hasUnsavedChanges ? "bg-amber-500 animate-pulse" : "bg-emerald-500"}`}></span>
                                                        {hasUnsavedChanges ? "Unsaved changes" : "Saved"}
                                                        <span className="mx-1.5 opacity-30 text-slate-600">•</span>
                                                        <span className="font-mono">{draftContent.length.toLocaleString()} chars</span>
                                                 </div>
                                                 <div className="flex items-center gap-3">
                                                        <button
                                                               onClick={() => {
                                                                      setDraftContent(loadedContent);
                                                               }}
                                                               disabled={!hasUnsavedChanges}
                                                               className="rounded-lg px-4 py-2 text-[12px] font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-colors disabled:opacity-30"
                                                        >
                                                               捨棄
                                                        </button>
                                                        <button
                                                               onClick={saveDocument}
                                                               disabled={saving || !hasUnsavedChanges}
                                                               className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[12px] font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50 shadow-lg shadow-primary/10"
                                                        >
                                                               <span className="material-symbols-outlined text-[16px]">save</span>
                                                               {saving ? "儲存中..." : "儲存設定"}
                                                        </button>
                                                 </div>
                                          </div>
                                   </div>
                            ) : (
                                   <div className="flex-1 flex items-center justify-center p-12">
                                          <div className="max-w-sm text-center">
                                                 <div className="w-16 h-16 rounded-xl bg-slate-900/50 border border-slate-700 flex items-center justify-center text-slate-500 mx-auto mb-6">
                                                        <span className="material-symbols-outlined text-[32px]">groups</span>
                                                 </div>
                                                 <h3 className="text-xl font-semibold text-slate-200 mb-2">未選擇角色</h3>
                                                 <p className="text-[13px] text-slate-500 leading-relaxed">
                                                        從左側欄選擇要編輯的角色，或建立新角色進行實驗。
                                                 </p>
                                          </div>
                                   </div>
                            )}
                     </main>

                     <ConfirmModal
                            open={deletePersonaTarget !== null}
                            title="刪除角色"
                            message={`確定要刪除角色「${deletePersonaTarget?.persona_id}」嗎？此操作無法復原。`}
                            confirmLabel="刪除"
                            danger
                            onConfirm={confirmDeletePersona}
                            onCancel={() => setDeletePersonaTarget(null)}
                     />
              </div>
       );
}

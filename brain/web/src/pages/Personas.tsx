import { useEffect, useState } from "react";
import Markdown from "react-markdown";
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

       const coreDocs = selectedPersona
              ? [
                     { path: selectedPersona.path, label: "SOUL.md", icon: "psychology" },
                     { path: `personas/${selectedPersona.persona_id}/AGENTS.md`, label: "AGENTS.md", icon: "group_work" },
                     { path: `personas/${selectedPersona.persona_id}/TOOLS.md`, label: "TOOLS.md", icon: "build" },
                     { path: `personas/${selectedPersona.persona_id}/MEMORY.md`, label: "MEMORY.md", icon: "memory" },
              ].filter(
                     (d) =>
                            !selectedPersona.is_default ||
                            d.label === "SOUL.md" ||
                            d.label === "AGENTS.md" ||
                            d.label === "TOOLS.md" ||
                            d.label === "MEMORY.md"
              )
              : [];

       // Default project uses global paths
       if (selectedPersona && selectedPersona.is_default && projectId === "default") {
              coreDocs[1].path = "AGENTS.md";
              coreDocs[2].path = "TOOLS.md";
              coreDocs[3].path = "MEMORY.md";
       }

       return (
              <div className="flex h-full w-full overflow-hidden bg-background">
                     {/* Contextual Sidebar */}
                     <aside className="w-[300px] lg:w-[340px] flex-shrink-0 border-r border-slate-800/60 bg-slate-950/30 flex flex-col hidden md:flex">
                            {/* Sidebar Header */}
                            <div className="px-5 py-5 border-b border-slate-800/60 flex items-center justify-between shrink-0 bg-slate-900/20">
                                   <h2 className="text-sm font-bold tracking-widest uppercase text-slate-300">Personas Hub</h2>
                                   <button
                                          onClick={() => loadPersonas(selectedPersona?.persona_id)}
                                          disabled={loadingList}
                                          className="flex h-7 w-7 items-center justify-center rounded border border-transparent text-slate-400 hover:bg-slate-800 hover:text-white transition-colors disabled:opacity-50"
                                          title="Refresh"
                                   >
                                          <span className={`material-symbols-outlined text-[16px] ${loadingList ? "animate-spin" : ""}`}>
                                                 refresh
                                          </span>
                                   </button>
                            </div>

                            <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none">
                                   {/* Persona List */}
                                   <div>
                                          <div className="flex items-center justify-between mb-3 text-xs font-bold text-slate-500 uppercase tracking-widest">
                                                 <div className="flex items-center gap-2">
                                                        <span className="material-symbols-outlined text-[14px]">groups</span>
                                                        <span>{personas.length} Personas</span>
                                                 </div>
                                          </div>
                                          <div className="grid gap-2">
                                                 {personas.map((persona) => (
                                                        <div
                                                               key={persona.persona_id}
                                                               className={`rounded-xl border p-3 text-left transition-all cursor-pointer ${selectedPersona?.persona_id === persona.persona_id
                                                                             ? "border-primary/40 bg-primary/10 shadow-sm"
                                                                             : "border-slate-800/60 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-800/40"
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
                                                                                           def
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
                                   <div className="rounded-xl border border-slate-800/80 bg-slate-900/30 p-4 space-y-3">
                                          <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Add Persona</h3>
                                          <div className="space-y-2">
                                                 <input
                                                        value={newPersonaId}
                                                        onChange={(event) => setNewPersonaId(event.target.value)}
                                                        placeholder="ID (e.g. support)"
                                                        className="w-full rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-white placeholder:text-slate-600 focus:border-primary/50 focus:outline-none focus:bg-slate-900 transition-colors"
                                                        title="Unique Persona ID (used in folder path)"
                                                 />
                                                 <input
                                                        value={newPersonaLabel}
                                                        onChange={(event) => setNewPersonaLabel(event.target.value)}
                                                        placeholder="Name (e.g. Support Bot)"
                                                        className="w-full rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-white placeholder:text-slate-600 focus:border-primary/50 focus:outline-none focus:bg-slate-900 transition-colors"
                                                        title="Display Name (only applied to Blank Template)"
                                                 />
                                                 <select
                                                        value={templateSourceId}
                                                        onChange={(event) => setTemplateSourceId(event.target.value)}
                                                        className="w-full rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-300 focus:border-primary/50 focus:outline-none focus:bg-slate-900 transition-colors"
                                                        title="Select a template or an existing persona to copy configuration from"
                                                 >
                                                        <option value="">-- Blank Template --</option>
                                                        {personas.map((persona) => (
                                                               <option key={persona.persona_id} value={persona.persona_id}>
                                                                      Copy from {persona.persona_id}
                                                               </option>
                                                        ))}
                                                 </select>
                                          </div>
                                          <button
                                                 onClick={handleCreateOrClone}
                                                 disabled={creatingPersona || cloningPersona || !newPersonaId.trim()}
                                                 className="w-full rounded-md bg-slate-800 text-slate-300 px-3 py-2 text-xs font-bold hover:bg-slate-700 hover:text-white transition-colors disabled:opacity-50 uppercase tracking-widest"
                                          >
                                                 {(creatingPersona || cloningPersona) ? "Creating..." : "Create"}
                                          </button>
                                   </div>
                            </div>
                     </aside>

                     {/* Main Editor Content */}
                     <main className="flex-1 flex flex-col min-w-0 bg-background relative">
                            {status && (
                                   <div className="p-4 shrink-0 shadow-sm z-10 border-b border-slate-800/30 bg-background/80 backdrop-blur-sm">
                                          <StatusAlert type={status.type} message={status.message} />
                                   </div>
                            )}

                            {selectedPersona ? (
                                   <div className="flex-1 flex flex-col min-h-0 p-4 lg:p-6 lg:pl-8">
                                          <div className="flex flex-col gap-4 mb-4 shrink-0">
                                                 <div className="flex items-end justify-between">
                                                        <div className="flex items-center gap-3">
                                                               <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center text-primary border border-primary/30">
                                                                      <span className="material-symbols-outlined">psychology</span>
                                                               </div>
                                                               <div>
                                                                      <h3 className="text-2xl font-bold text-white leading-tight">
                                                                             {selectedPersona.label || selectedPersona.persona_id}
                                                                      </h3>
                                                                      <div className="flex items-center gap-2 mt-0.5">
                                                                             <span className="text-xs font-mono text-slate-500">{selectedPath}</span>
                                                                      </div>
                                                               </div>
                                                        </div>
                                                        <div className="flex items-center gap-4 shrink-0">
                                                               <div className="flex rounded-md border border-slate-700 overflow-hidden bg-slate-900">
                                                                      {(["edit", "split", "preview"] as EditorMode[]).map((mode) => (
                                                                             <button
                                                                                    key={mode}
                                                                                    onClick={() => setEditorMode(mode)}
                                                                                    className={`px-3 py-1.5 text-xs font-semibold transition-colors ${editorMode === mode
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

                                                 <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar border-b border-slate-800/60 pb-3">
                                                        {coreDocs.map((doc) => (
                                                               <button
                                                                      key={doc.path}
                                                                      onClick={() => openDocument(doc.path)}
                                                                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${selectedPath === doc.path
                                                                                    ? "bg-primary text-white shadow-shadow-primary/20"
                                                                                    : "bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700"
                                                                             }`}
                                                               >
                                                                      <span className={`material-symbols-outlined text-[16px] ${selectedPath === doc.path ? "text-white" : ""}`}>{doc.icon}</span>
                                                                      {doc.label}
                                                               </button>
                                                        ))}
                                                 </div>
                                          </div>

                                          <div className="flex-1 min-h-0 relative mb-4 rounded-xl border border-slate-800/50 bg-slate-950/30 overflow-hidden shadow-inner flex">
                                                 {loadingDocument && (
                                                        <div className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm z-10 flex items-center justify-center">
                                                               <div className="flex items-center gap-2 text-primary font-bold">
                                                                      <span className="material-symbols-outlined animate-spin">refresh</span>
                                                                      Loading...
                                                               </div>
                                                        </div>
                                                 )}
                                                 {editorMode === "edit" || editorMode === "split" ? (
                                                        <textarea
                                                               value={draftContent}
                                                               onChange={(event) => setDraftContent(event.target.value)}
                                                               className={`h-full w-full bg-transparent p-5 text-sm leading-7 text-slate-200 placeholder:text-slate-600 focus:outline-none font-mono resize-none ${editorMode === "split" ? "border-r border-slate-800/50" : ""
                                                                      }`}
                                                        />
                                                 ) : null}
                                                 {editorMode === "preview" || editorMode === "split" ? (
                                                        <div className="h-full w-full p-6 overflow-y-auto prose-container bg-slate-900/20">
                                                               <MarkdownPreview content={draftContent} />
                                                        </div>
                                                 ) : null}
                                          </div>

                                          <div className="flex items-center justify-between shrink-0 pt-2 px-1 border-t border-slate-800/50 pt-4">
                                                 <div className="flex items-center gap-2 text-xs text-slate-500">
                                                        <span className={`w-2 h-2 rounded-full ${hasUnsavedChanges ? "bg-amber-500 animate-pulse" : "bg-emerald-500"}`}></span>
                                                        {hasUnsavedChanges ? "Unsaved changes" : "Saved"}
                                                        <span className="mx-2 opacity-30">•</span>
                                                        {draftContent.length.toLocaleString()} chars
                                                 </div>
                                                 <div className="flex items-center gap-3">
                                                        <button
                                                               onClick={() => {
                                                                      setDraftContent(loadedContent);
                                                               }}
                                                               disabled={!hasUnsavedChanges}
                                                               className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white hover:bg-slate-800 transition-colors disabled:opacity-30"
                                                        >
                                                               Discard
                                                        </button>
                                                        <button
                                                               onClick={saveDocument}
                                                               disabled={saving || !hasUnsavedChanges}
                                                               className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-50 shadow-lg shadow-primary/10"
                                                        >
                                                               <span className="material-symbols-outlined text-[18px]">save</span>
                                                               {saving ? "Saving..." : "Save Config"}
                                                        </button>
                                                 </div>
                                          </div>
                                   </div>
                            ) : (
                                   <div className="flex-1 flex items-center justify-center p-12">
                                          <div className="max-w-md text-center">
                                                 <div className="w-20 h-20 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-600 mx-auto mb-6">
                                                        <span className="material-symbols-outlined text-[40px]">groups</span>
                                                 </div>
                                                 <h3 className="text-xl font-bold text-slate-300 mb-2">No Persona Selected</h3>
                                                 <p className="text-sm text-slate-500">
                                                        Select a persona from the left sidebar to edit its core configuration, or create a brand new persona to experiment with.
                                                 </p>
                                          </div>
                                   </div>
                            )}
                     </main>

                     <ConfirmModal
                            open={deletePersonaTarget !== null}
                            title="Delete Persona"
                            message={`確定要刪除 persona「${deletePersonaTarget?.persona_id}」嗎？此操作無法復原。`}
                            confirmLabel="Delete"
                            danger
                            onConfirm={confirmDeletePersona}
                            onCancel={() => setDeletePersonaTarget(null)}
                     />
              </div>
       );
}

function MarkdownPreview({ content }: { content: string }) {
       return (
              <Markdown
                     components={{
                            h1: ({ children }) => <h1 className="text-2xl font-bold text-white mb-4 mt-6 first:mt-0">{children}</h1>,
                            h2: ({ children }) => <h2 className="text-xl font-bold text-white mb-3 mt-5 border-b border-slate-800 pb-2">{children}</h2>,
                            h3: ({ children }) => <h3 className="text-lg font-semibold text-white mb-2 mt-4">{children}</h3>,
                            p: ({ children }) => <p className="text-sm leading-7 text-slate-300 mb-4">{children}</p>,
                            ul: ({ children }) => <ul className="list-disc list-inside text-sm text-slate-300 mb-4 space-y-1.5 pl-2">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal list-inside text-sm text-slate-300 mb-4 space-y-1.5 pl-2">{children}</ol>,
                            li: ({ children }) => <li className="text-sm text-slate-300">{children}</li>,
                            code: ({ children, className }) => {
                                   const isBlock = className?.includes("language-");
                                   if (isBlock) {
                                          return <code className="block rounded-lg bg-slate-950 p-4 text-sm text-primary/80 font-mono overflow-x-auto mb-4 border border-slate-800">{children}</code>;
                                   }
                                   return <code className="rounded bg-slate-800 px-1.5 py-0.5 text-sm text-primary/80 font-mono">{children}</code>;
                            },
                            pre: ({ children }) => <pre className="mb-4">{children}</pre>,
                            blockquote: ({ children }) => <blockquote className="border-l-4 border-primary/40 pl-4 italic text-slate-400 mb-4 bg-primary/5 py-2 pr-4 rounded-r-lg">{children}</blockquote>,
                            a: ({ children, href }) => <a href={href} className="text-primary hover:text-primary/80 underline decoration-primary/30 underline-offset-2 transition-colors" target="_blank" rel="noopener noreferrer">{children}</a>,
                            hr: () => <hr className="border-slate-800 my-6" />,
                            strong: ({ children }) => <strong className="font-bold text-slate-200">{children}</strong>,
                            table: ({ children }) => <div className="overflow-x-auto mb-4"><table className="w-full text-sm text-slate-300 border-collapse">{children}</table></div>,
                            th: ({ children }) => <th className="border border-slate-700 px-4 py-2.5 text-left font-semibold text-slate-200 bg-slate-800/50">{children}</th>,
                            td: ({ children }) => <td className="border border-slate-700 px-4 py-2 bg-slate-900/20">{children}</td>,
                     }}
              >
                     {content}
              </Markdown>
       );
}

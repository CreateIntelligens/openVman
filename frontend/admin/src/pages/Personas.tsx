import { useEffect, useState } from "react";
import {
       AvatarCharacter,
       AvatarMascot,
       clonePersona,
       createPersona,
       deletePersona,
       fetchAvatarCharacters,
       fetchAvatarMascots,
       fetchPersonas,
       fetchKnowledgeDocument,
       PersonaSummary,
       saveKnowledgeDocument,
       setPersonaAvatar,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import ConfirmModal from "../components/ConfirmModal";
import Select from "../components/Select";
import PersonaCreateForm from "../components/personas/PersonaCreateForm";
import PersonaEditor from "../components/personas/PersonaEditor";
import PersonaEmptyState from "../components/personas/PersonaEmptyState";
import PersonaList from "../components/personas/PersonaList";
import { useUnsavedChanges } from "../context/NavigationGuardContext";
import { useProject } from "../context/ProjectContext";
import { useLocalStorageState } from "../hooks/useLocalStorageState";

type EditorMode = "edit" | "preview" | "split";
const EDITOR_MODES: readonly EditorMode[] = ["edit", "split", "preview"];
type Status = { type: "success" | "error"; message: string } | null;
type AvatarBindingOption = Pick<AvatarCharacter, "char_id" | "label">;

function buildAvatarBindingOptions(
       characters: AvatarCharacter[],
       mascots: AvatarMascot[],
): AvatarBindingOption[] {
       return [
              ...characters.map((character) => ({
                     char_id: character.char_id,
                     label: `${character.label || character.char_id} (2D)`,
              })),
              ...mascots.map((mascot) => ({
                     char_id: mascot.mascot_id,
                     label: `${mascot.label || mascot.mascot_id} (3D VRM)`,
              })),
       ];
}

export default function Personas() {
       const { projectId } = useProject();
       const [personas, setPersonas] = useState<PersonaSummary[]>([]);
       const [newPersonaId, setNewPersonaId] = useState("");
       const [newPersonaLabel, setNewPersonaLabel] = useState("");
       const [templateSourceId, setTemplateSourceId] = useState("");

       const [selectedPersona, setSelectedPersona] = useState<PersonaSummary | null>(null);
       const [avatarChars, setAvatarChars] = useState<AvatarBindingOption[]>([]);

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

       const [editorMode, setEditorMode] = useLocalStorageState<EditorMode>(
              "admin.personas.editor_mode",
              "edit",
              EDITOR_MODES,
       );
       const [deletePersonaTarget, setDeletePersonaTarget] = useState<PersonaSummary | null>(null);

       const hasUnsavedChanges = draftContent !== loadedContent;
       useUnsavedChanges("persona-editor", hasUnsavedChanges, "Persona 文件");

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

       useEffect(() => {
              Promise.all([
                     fetchAvatarCharacters().catch(() => ({ characters: [] })),
                     fetchAvatarMascots().catch(() => ({ mascots: [] })),
              ]).then(([charsRes, mascotsRes]) => {
                     setAvatarChars(
                            buildAvatarBindingOptions(charsRes.characters, mascotsRes.mascots),
                     );
              });
       }, []);

       const onBindAvatar = async (personaId: string, charId: string | null) => {
              try {
                     await setPersonaAvatar(personaId, charId);
                     setStatus({ type: "success", message: "已更新虛擬人綁定" });
                     await loadPersonas(personaId);
              } catch (error) {
                     setStatus({
                            type: "error",
                            message: getErrorMessage(error),
                     });
              }
       };

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
              <div className="flex h-full w-full overflow-hidden bg-surface dark:bg-background-dark">
                     {/* Contextual Sidebar */}
                     <aside className="w-[18.75rem] lg:w-[20rem] flex-shrink-0 border-r border-border bg-surface-raised dark:bg-surface/30 flex flex-col hidden md:flex z-10">
                            {/* Sidebar Header */}
                            <div className="px-5 py-5 border-b border-border flex items-center justify-between shrink-0 bg-surface dark:bg-surface-sunken/20">
                                   <div className="flex items-center gap-2.5">
                                          <div className="w-6 h-6 rounded flex items-center justify-center bg-surface-sunken text-content-muted">
                                                 <span className="material-symbols-outlined text-[0.875rem]">groups_2</span>
                                          </div>
                                          <h2 className="text-[0.8125rem] font-semibold tracking-wide text-content">角色管理</h2>
                                   </div>
                                   <button
                                          onClick={() => loadPersonas(selectedPersona?.persona_id)}
                                          disabled={loadingList}
                                          className="flex h-7 w-7 items-center justify-center rounded-md text-content-muted hover:bg-surface-sunken hover:text-content transition-colors disabled:opacity-50"
                                          title="重新整理"
                                   >
                                          <span className={`material-symbols-outlined text-[1rem] ${loadingList ? "animate-spin text-content" : ""}`}>
                                                 refresh
                                          </span>
                                   </button>
                            </div>

                            <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none no-scrollbar">
                                   <PersonaList
                                          personas={personas}
                                          selectedPersonaId={selectedPersona?.persona_id}
                                          deletingPersonaId={deletingPersonaId}
                                          onSelect={(persona) => {
                                                 setSelectedPersona(persona);
                                                 openDocument(persona.path);
                                          }}
                                          onDelete={setDeletePersonaTarget}
                                   />

                                   <hr className="border-border " />

                                   <PersonaCreateForm
                                          personas={personas}
                                          newPersonaId={newPersonaId}
                                          newPersonaLabel={newPersonaLabel}
                                          templateSourceId={templateSourceId}
                                          creatingPersona={creatingPersona}
                                          cloningPersona={cloningPersona}
                                          onNewPersonaIdChange={setNewPersonaId}
                                          onNewPersonaLabelChange={setNewPersonaLabel}
                                          onTemplateSourceIdChange={setTemplateSourceId}
                                          onSubmit={handleCreateOrClone}
                                   />
                            </div>
                     </aside>

                     {/* Main Editor Content */}
                     <main className="flex-1 flex flex-col min-w-0 bg-surface dark:bg-background-dark relative overflow-hidden">
                            {status && (
                                   <div className="p-4 shrink-0 shadow-sm z-20 border-b border-border ">
                                          <StatusAlert type={status.type} message={status.message} />
                                   </div>
                            )}

                            {selectedPersona ? (
                                   <>
                                          <PersonaAvatarSelector
                                                 characters={avatarChars}
                                                 persona={selectedPersona}
                                                 onBind={onBindAvatar}
                                          />
                                          <PersonaEditor
                                                 title={selectedPersona.label || selectedPersona.persona_id}
                                                 selectedPath={selectedPath}
                                                 draftContent={draftContent}
                                                 coreDocs={coreDocs}
                                                 editorMode={editorMode}
                                                 loadingDocument={loadingDocument}
                                                 saving={saving}
                                                 hasUnsavedChanges={hasUnsavedChanges}
                                                 onEditorModeChange={setEditorMode}
                                                 onOpenDocument={openDocument}
                                                 onDraftContentChange={setDraftContent}
                                                 onDiscard={() => setDraftContent(loadedContent)}
                                                 onSave={saveDocument}
                                          />
                                   </>
                            ) : <PersonaEmptyState />}
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

function getErrorMessage(error: unknown): string {
       return error instanceof Error ? error.message : String(error);
}

function PersonaAvatarSelector({
       characters,
       persona,
       onBind,
}: {
       characters: AvatarBindingOption[];
       persona: PersonaSummary;
       onBind: (personaId: string, charId: string | null) => Promise<void>;
}) {
       const options = [
              { value: "", label: "（未綁定）" },
              ...characters.map((character) => ({
                     value: character.char_id,
                     label: character.label,
              })),
       ];

       return (
              <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-surface-raised dark:bg-surface-sunken/10">
                     <span className="text-sm text-content-muted font-medium">虛擬人模型：</span>
                     <Select
                            ariaLabel="虛擬人模型"
                            value={persona.avatar_char_id ?? ""}
                            options={options}
                            onChange={(value) => onBind(persona.persona_id, value || null)}
                            className="min-w-[10rem]"
                     />
              </div>
       );
}

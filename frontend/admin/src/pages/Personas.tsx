import { useEffect, useState } from "react";
import {
       AvatarCharacter,
       clonePersona,
       createPersona,
       deletePersona,
       fetchAvatarCharacters,
       fetchPersonas,
       fetchKnowledgeDocument,
       PersonaSummary,
       saveKnowledgeDocument,
       setPersonaAvatar,
} from "../api";
import StatusAlert from "../components/StatusAlert";
import { PageHeader } from "../components/app/PageHeader";
import ConfirmModal from "../components/ConfirmModal";
import Select from "../components/Select";
import PersonaCreateForm from "../components/personas/PersonaCreateForm";
import PersonaEditor from "../components/personas/PersonaEditor";
import PersonaEmptyState from "../components/personas/PersonaEmptyState";
import PersonaList from "../components/personas/PersonaList";
import { useNavigationGuard, useUnsavedChanges } from "../context/NavigationGuardContext";
import { useProject } from "../context/ProjectContext";
import { useLocalStorageState } from "../hooks/useLocalStorageState";
import { useMobileTreeDrawer } from "../hooks/useMobileTreeDrawer";

type EditorMode = "edit" | "preview" | "split";
const EDITOR_MODES: readonly EditorMode[] = ["edit", "split", "preview"];
type Status = { type: "success" | "error"; message: string } | null;
type AvatarBindingOption = Pick<AvatarCharacter, "char_id" | "label">;

// 前台舞台只有 2D 影片人物，虛擬人只能綁人物；小助理不是舞台上的角色。
function buildAvatarBindingOptions(
       characters: AvatarCharacter[],
): AvatarBindingOption[] {
       return characters.map((character) => ({
              char_id: character.char_id,
              label: character.label || character.char_id,
       }));
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
       const { requestNavigation } = useNavigationGuard();

       // 重抓清單。keepId 的角色還在就只換成新資料、不重開文件：存檔、綁虛擬人、
       // 重新整理、刪別的角色之後，草稿和正在看的分頁都要留著。不在了才改開第一個。
       const loadPersonas = async (keepId?: string): Promise<PersonaSummary[]> => {
              setLoadingList(true);
              try {
                     const response = await fetchPersonas();
                     setPersonas(response.personas);
                     const kept = response.personas.find((p) => p.persona_id === keepId);
                     if (kept) {
                            setSelectedPersona(kept);
                     } else {
                            await openPersona(response.personas[0] ?? null);
                     }
                     return response.personas;
              } catch (error) {
                     setStatus({ type: "error", message: String(error) });
                     return [];
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

       const personaDrawer = useMobileTreeDrawer("關閉角色清單");

       const openPersona = async (persona: PersonaSummary | null) => {
              setSelectedPersona(persona);
              if (persona?.path) {
                     await openDocument(persona.path);
                     return;
              }
              setSelectedPath("");
              setDraftContent("");
              setLoadedContent("");
       };

       // 使用者主動換角色或換文件：有未存的修改先問，不直接蓋掉。
       // onConfirmed 只在真的要換時才跑，例如關手機抽屜；按取消就留在原地。
       const selectPersona = (persona: PersonaSummary, onConfirmed?: () => void) => {
              requestNavigation(() => {
                     onConfirmed?.();
                     void openPersona(persona);
              });
       };

       const selectDocument = (path: string) => {
              if (path === selectedPath) return;
              requestNavigation(() => void openDocument(path));
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

       const openCreatedPersona = async (personaId: string) => {
              const list = await loadPersonas(selectedPersona?.persona_id);
              const created = list.find((p) => p.persona_id === personaId);
              if (created) selectPersona(created);
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
                            await openCreatedPersona(response.persona.persona_id);
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
                            await openCreatedPersona(response.persona.persona_id);
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
                     await loadPersonas(
                            selectedPersona?.persona_id === persona.persona_id
                                   ? undefined
                                   : selectedPersona?.persona_id,
                     );
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
              fetchAvatarCharacters()
                     .catch(() => ({ characters: [] }))
                     .then((charsRes) => {
                            setAvatarChars(buildAvatarBindingOptions(charsRes.characters));
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
                     {/* 手機上側欄是抽屜：新增、複製、刪除角色都在裡面，由頁首的「管理角色」打開。 */}
                     {personaDrawer.mobileTreeOpen && (
                            <button
                                   type="button"
                                   className="fixed inset-0 z-40 bg-black/40 md:hidden"
                                   onClick={personaDrawer.closeMobileTree}
                                   aria-label="關閉角色清單"
                            />
                     )}
                     <aside
                            ref={personaDrawer.mobileTreePanelRef}
                            id="persona-list-panel"
                            aria-label="角色清單"
                            aria-modal={personaDrawer.mobileTreeOpen ? "true" : undefined}
                            role={personaDrawer.mobileTreeOpen ? "dialog" : undefined}
                            className={`fixed inset-y-0 left-0 z-50 w-[min(18.75rem,85vw)] flex-shrink-0 flex-col border-r border-border bg-surface-raised md:relative md:z-10 md:flex md:w-[18.75rem] md:dark:bg-surface/30 lg:w-[20rem] ${
                                   personaDrawer.mobileTreeOpen ? "flex" : "hidden"
                            }`}
                     >
                            {/* Sidebar Header */}
                            <div className="px-5 py-5 border-b border-border flex items-center justify-between shrink-0 bg-surface dark:bg-surface-sunken/20">
                                   <h2 className="section-title md:hidden">管理角色</h2>
                                   <div className="hidden items-center gap-2.5 md:flex">
                                          <div className="w-8 h-8 rounded flex items-center justify-center bg-surface-sunken text-content-muted">
                                                 <span className="material-symbols-outlined text-[1.25rem]">groups_2</span>
                                          </div>
                                          <h1 className="page-title">角色管理</h1>
                                   </div>
                                   <div className="flex items-center gap-1">
                                          <button
                                                 onClick={() => void loadPersonas(selectedPersona?.persona_id)}
                                                 disabled={loadingList}
                                                 className="flex h-7 w-7 items-center justify-center rounded-md text-content-muted hover:bg-surface-sunken hover:text-content transition-colors disabled:opacity-50"
                                                 title="重新整理"
                                                 aria-label="重新整理角色清單"
                                          >
                                                 <span className={`material-symbols-outlined text-[1rem] ${loadingList ? "animate-spin text-content" : ""}`}>
                                                        refresh
                                                 </span>
                                          </button>
                                          <button
                                                 type="button"
                                                 onClick={personaDrawer.closeMobileTree}
                                                 aria-label="關閉角色清單"
                                                 className="flex h-7 w-7 items-center justify-center rounded-md text-content-muted hover:bg-surface-sunken hover:text-content transition-colors md:hidden"
                                          >
                                                 <span className="material-symbols-outlined text-[1.125rem]">close</span>
                                          </button>
                                   </div>
                            </div>

                            <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none no-scrollbar">
                                   <PersonaList
                                          personas={personas}
                                          selectedPersonaId={selectedPersona?.persona_id}
                                          deletingPersonaId={deletingPersonaId}
                                          onSelect={(persona) => selectPersona(persona, personaDrawer.closeMobileTree)}
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
                            {/* 手機看不到側欄：主標題與切換角色放在這一列，桌面版由側欄負責。 */}
                            <PageHeader
                                   title="角色管理"
                                   sticky={false}
                                   className="md:hidden"
                                   actions={(
                                          <>
                                                 <label className="flex min-w-0 items-center gap-2 text-sm text-content-muted">
                                                        <span className="shrink-0">角色</span>
                                                        <select
                                                               className="input min-w-0 flex-1 py-1.5"
                                                               aria-label="切換角色"
                                                               value={selectedPersona?.persona_id ?? ""}
                                                               onChange={(event) => {
                                                                      const persona = personas.find((item) => item.persona_id === event.target.value);
                                                                      if (persona) selectPersona(persona);
                                                               }}
                                                        >
                                                               {personas.map((persona) => (
                                                                      <option key={persona.persona_id} value={persona.persona_id}>
                                                                             {persona.label || persona.persona_id}
                                                                      </option>
                                                               ))}
                                                        </select>
                                                 </label>
                                                 <button
                                                        type="button"
                                                        onClick={personaDrawer.openMobileTree}
                                                        aria-label="管理角色"
                                                        aria-controls="persona-list-panel"
                                                        aria-expanded={personaDrawer.mobileTreeOpen}
                                                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-content-subtle hover:bg-surface-sunken hover:text-primary"
                                                 >
                                                        <span className="material-symbols-outlined text-[1.125rem]">manage_accounts</span>
                                                 </button>
                                          </>
                                   )}
                            />
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
                                                 onOpenDocument={selectDocument}
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

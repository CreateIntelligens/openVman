import { useEffect, useRef, useState } from "react";
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
import PersonaForm from "../components/personas/PersonaForm";
import SegmentedControl from "../components/SegmentedControl";
import PersonaList from "../components/personas/PersonaList";
import { useNavigationGuard, useUnsavedChanges } from "../context/NavigationGuardContext";
import { useAuth } from "../context/AuthContext";
import { useProject } from "../context/ProjectContext";
import { useLocalStorageState } from "../hooks/useLocalStorageState";
import { useMobileTreeDrawer } from "../hooks/useMobileTreeDrawer";
import { isVendorUser } from "../utils/accountPermissions";
import { generateAssetId } from "../utils/generateAssetId";

type EditorMode = "edit" | "preview" | "split";
const EDITOR_MODES: readonly EditorMode[] = ["edit", "split", "preview"];
// 表格模式只露出人設欄位；原始文件模式是四份文件直接編輯，只給內部帳號。
type ViewMode = "form" | "document";
const VIEW_MODES: readonly ViewMode[] = ["form", "document"];
const VIEW_MODE_OPTIONS: Array<{ id: ViewMode; label: string }> = [
       { id: "form", label: "表格" },
       { id: "document", label: "原始文件" },
];
type Status = { type: "success" | "error"; message: string } | null;
type AvatarBindingOption = Pick<AvatarCharacter, "char_id" | "label">;

// 前台舞台只有 2D 影片人物，虛擬人只能綁人物；小助理不是舞台上的角色。
const PERSONA_DOC_LABELS: Record<string, string> = {
       "SOUL.md": "個性與說話方式",
       "AGENTS.md": "工作規則",
       "TOOLS.md": "工具使用說明",
       "MEMORY.md": "長期記憶",
};

function personaDocLabel(path: string): string {
       const fileName = path.split("/").pop() ?? path;
       return PERSONA_DOC_LABELS[fileName] ?? fileName;
}

function buildAvatarBindingOptions(
       characters: AvatarCharacter[],
): AvatarBindingOption[] {
       return characters.map((character) => ({
              char_id: character.char_id,
              label: character.label || character.char_id,
       }));
}

export default function Personas() {
       const { projectId, projects } = useProject();
       const { account } = useAuth();
       const vendor = Boolean(account && isVendorUser(account));
       const project = projects?.find((item) => item.project_id === projectId);
       // 廠商要明確授權才可改；內部帳號以 Backend 回報的權限為準（舊版沒回報時照舊可改，寫入仍由後端把關）。
       const canEditKnowledge = vendor
              ? project?.can_edit_knowledge === true
              : project?.can_edit_knowledge !== false;
       const readOnly = !canEditKnowledge;
       const canEditGuardrails = !vendor && project?.can_edit_features === true;
       const pageTitle = "角色管理";
       const [personas, setPersonas] = useState<PersonaSummary[]>([]);
       const [newPersonaId, setNewPersonaId] = useState("");
       const [newPersonaLabel, setNewPersonaLabel] = useState("");
       const [templateSourceId, setTemplateSourceId] = useState("");

       const [selectedPersona, setSelectedPersona] = useState<PersonaSummary | null>(null);
       const [avatarChars, setAvatarChars] = useState<AvatarBindingOption[]>([]);

       // Document Editor State
       const latestDocumentRequest = useRef(0);
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
       const [storedViewMode, setStoredViewMode] = useLocalStorageState<ViewMode>(
              "admin.personas.view_mode",
              "form",
              VIEW_MODES,
       );
       const viewMode: ViewMode = vendor ? "form" : storedViewMode;

       const hasUnsavedChanges = draftContent !== loadedContent;
       useUnsavedChanges("persona-editor", hasUnsavedChanges, "角色文件");
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
              const requestId = ++latestDocumentRequest.current;
              setLoadingDocument(true);
              setStatus(null);
              try {
                     const response = await fetchKnowledgeDocument(path);
                     if (requestId !== latestDocumentRequest.current) return;
                     setSelectedPath(response.path);
                     setDraftContent(response.content);
                     setLoadedContent(response.content);
              } catch (error) {
                     if (requestId === latestDocumentRequest.current) {
                            setStatus({ type: "error", message: String(error) });
                     }
              } finally {
                     if (requestId === latestDocumentRequest.current) setLoadingDocument(false);
              }
       };

       const personaDrawer = useMobileTreeDrawer("關閉角色清單");

       const openPersona = async (persona: PersonaSummary | null, mode: ViewMode = viewMode) => {
              setSelectedPersona(persona);
              // 表格模式自己讀文件；原始文件的編輯器只在切過去時才載入。
              if (mode === "document" && persona?.path) {
                     await openDocument(persona.path);
                     return;
              }
              ++latestDocumentRequest.current;
              setLoadingDocument(false);
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
              if (!selectedPath || readOnly || loadingDocument) return;
              const requestId = latestDocumentRequest.current;

              setSaving(true);
              setStatus(null);

              try {
                     await saveKnowledgeDocument(selectedPath, draftContent);
                     if (requestId !== latestDocumentRequest.current) return;
                     setStatus({ type: "success", message: `已儲存「${personaDocLabel(selectedPath)}」` });
                     setLoadedContent(draftContent);
                     await loadPersonas(selectedPersona?.persona_id);
              } catch (error) {
                     setStatus({ type: "error", message: String(error) });
              } finally {
                     setSaving(false);
              }
       };

       const changeViewMode = (next: ViewMode) => {
              if (next === viewMode) return;
              requestNavigation(() => {
                     setStatus(null);
                     setStoredViewMode(next);
                     void openPersona(selectedPersona, next);
              });
       };

       const openCreatedPersona = async (personaId: string) => {
              const list = await loadPersonas(selectedPersona?.persona_id);
              const created = list.find((p) => p.persona_id === personaId);
              if (created) selectPersona(created);
       };

       const handleCreateOrClone = async () => {
              const typedId = newPersonaId.trim();
              if (typedId && !/^[A-Za-z0-9._-]{1,64}$/.test(typedId)) {
                     setStatus({ type: "error", message: "代號只能用英文、數字和 . _ -，或是留空讓系統產生。" });
                     return;
              }
              if (!typedId && !templateSourceId && !newPersonaLabel.trim()) {
                     setStatus({ type: "error", message: "請輸入角色名稱。" });
                     return;
              }
              const personaId = typedId || generateAssetId("persona");

              setStatus(null);

              // If a template is selected (not empty), clone that existing persona
              if (templateSourceId) {
                     setCloningPersona(true);
                     try {
                            const response = await clonePersona(templateSourceId, personaId);
                            setStatus({
                                   type: "success",
                                   message: `已複製成新角色「${response.persona.label || response.persona.persona_id}」。`,
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
                            const response = await createPersona(personaId, newPersonaLabel.trim());
                            setStatus({
                                   type: "success",
                                   message: `已建立角色「${response.persona.label || response.persona.persona_id}」。`,
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
                            message: `已刪除角色「${persona.label || persona.persona_id}」。`,
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
       }, [projectId, vendor]);

       useEffect(() => {
              if (vendor) return;
              fetchAvatarCharacters()
                     .catch(() => ({ characters: [] }))
                     .then((charsRes) => {
                            setAvatarChars(buildAvatarBindingOptions(charsRes.characters));
                     });
       }, [vendor]);

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
                     { path: selectedPersona.path ?? "SOUL.md", label: personaDocLabel("SOUL.md"), icon: "psychology" },
                     { path: `${docPrefix}AGENTS.md`, label: personaDocLabel("AGENTS.md"), icon: "group_work" },
                     { path: `${docPrefix}TOOLS.md`, label: personaDocLabel("TOOLS.md"), icon: "build" },
                     { path: `${docPrefix}MEMORY.md`, label: personaDocLabel("MEMORY.md"), icon: "memory" },
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
                                          <h1 className="page-title">{pageTitle}</h1>
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
                                          onDelete={vendor ? undefined : setDeletePersonaTarget}
                                   />

                                   {!vendor && <>
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
                                   </>}
                            </div>
                     </aside>

                     {/* Main Editor Content */}
                     <main className="flex-1 flex flex-col min-w-0 bg-surface dark:bg-background-dark relative overflow-hidden">
                            {/* 手機看不到側欄：主標題與切換角色放在這一列，桌面版由側欄負責。 */}
                            <PageHeader
                                   title={pageTitle}
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
                            {!vendor && selectedPersona && (
                                   <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-4 py-3 lg:px-8">
                                          <span className="text-sm text-content-muted">顯示方式</span>
                                          <SegmentedControl
                                                 label="顯示方式"
                                                 options={VIEW_MODE_OPTIONS}
                                                 value={viewMode}
                                                 onChange={changeViewMode}
                                          />
                                          <span className="text-sm text-content-subtle">
                                                 {viewMode === "form"
                                                        ? "依欄位填寫人設，不顯示工具說明和長期記憶。"
                                                        : "直接編輯整份文件，包含工具說明和長期記憶。"}
                                          </span>
                                   </div>
                            )}
                            {status && (
                                   <div className="p-4 shrink-0 shadow-sm z-20 border-b border-border ">
                                          <StatusAlert type={status.type} message={status.message} />
                                   </div>
                            )}

                            {selectedPersona ? (
                                   <>
                                          {!vendor && <PersonaAvatarSelector
                                                 characters={avatarChars}
                                                 persona={selectedPersona}
                                                 onBind={onBindAvatar}
                                          />}
                                          {viewMode === "form" ? (
                                          <PersonaForm
                                                 key={`${projectId}:${selectedPersona.persona_id}`}
                                                 persona={selectedPersona}
                                                 projectId={projectId}
                                                 canEditKnowledge={canEditKnowledge}
                                                 canEditGuardrails={canEditGuardrails}
                                                 onSaved={() => void loadPersonas(selectedPersona.persona_id)}
                                          />
                                          ) : (
                                          <PersonaEditor
                                                 title={selectedPersona.label || selectedPersona.persona_id}
                                                 selectedPath={selectedPath}
                                                 draftContent={draftContent}
                                                 coreDocs={coreDocs}
                                                 readOnly={readOnly}
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
                                          )}
                                   </>
                            ) : <PersonaEmptyState />}
                     </main>

                     <ConfirmModal
                            open={deletePersonaTarget !== null}
                            title="刪除角色"
                            message={`確定要刪除角色「${deletePersonaTarget?.label || deletePersonaTarget?.persona_id}」嗎？此操作無法復原。`}
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
                     <span className="text-sm text-content-muted font-medium">虛擬人：</span>
                     <Select
                            ariaLabel="虛擬人"
                            value={persona.avatar_char_id ?? ""}
                            options={options}
                            onChange={(value) => onBind(persona.persona_id, value || null)}
                            className="min-w-[10rem]"
                     />
              </div>
       );
}

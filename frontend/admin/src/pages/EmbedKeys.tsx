import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import {
  createEmbedKey,
  deleteEmbedKey,
  listEmbedKeys,
  parseDelimitedList,
  setEmbedKeyDisabled,
  updateEmbedKey,
  DEFAULT_DAILY_REQUEST_QUOTA,
  DEFAULT_RATE_LIMIT_PER_MINUTE,
  type EmbedKey,
} from "../api/embedKeys";
import { fetchProjects, type ProjectSummary } from "../api/projects";
import ConfirmModal from "../components/ConfirmModal";
import Select from "../components/Select";
import StatusAlert from "../components/StatusAlert";

interface KeyFormState {
  label: string;
  projectId: string;
  origins: string;
  defaultCharacterId: string;
  allowedCharacterIds: string;
  defaultPersonaId: string;
  defaultTtsProvider: string;
  defaultTtsVoice: string;
  rateLimitPerMinute: number;
  dailyRequestQuota: number;
}

type PageStatus = { type: "success" | "error"; message: string } | null;

const EMPTY_FORM: KeyFormState = {
  label: "",
  projectId: "",
  origins: "",
  defaultCharacterId: "",
  allowedCharacterIds: "",
  defaultPersonaId: "",
  defaultTtsProvider: "",
  defaultTtsVoice: "",
  rateLimitPerMinute: DEFAULT_RATE_LIMIT_PER_MINUTE,
  dailyRequestQuota: DEFAULT_DAILY_REQUEST_QUOTA,
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function formFromKey(key: EmbedKey): KeyFormState {
  return {
    label: key.label,
    projectId: key.project_id,
    origins: key.allowed_origins.join("\n"),
    defaultCharacterId: key.default_character_id,
    allowedCharacterIds: key.allowed_character_ids.join(", "),
    defaultPersonaId: key.default_persona_id,
    defaultTtsProvider: key.default_tts_provider,
    defaultTtsVoice: key.default_tts_voice,
    rateLimitPerMinute: key.rate_limit_per_minute,
    dailyRequestQuota: key.daily_request_quota,
  };
}

const inputClass =
  "w-full rounded-xl border border-border bg-surface-raised px-4 py-3 text-sm text-content placeholder:text-content-subtle focus:border-primary/40 focus:outline-none shadow-sm dark:shadow-none transition-all";
const labelClass = "mb-1 block text-xs text-content-muted";

export default function EmbedKeys() {
  const [keys, setKeys] = useState<EmbedKey[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [form, setForm] = useState<KeyFormState>(EMPTY_FORM);
  const [editingKeyId, setEditingKeyId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<EmbedKey | null>(null);
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<PageStatus>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const formErrorRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (!modalOpen) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    dialog.querySelector<HTMLInputElement>("#embed-key-label")?.focus();
    return () => {
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
      previousFocus?.focus();
    };
  }, [modalOpen]);

  useEffect(() => {
    if (formError) formErrorRef.current?.focus();
  }, [formError]);

  const reload = useCallback(async (showLoading = true): Promise<boolean> => {
    if (showLoading) setLoading(true);
    try {
      setKeys(await listEmbedKeys());
      return true;
    } catch (error) {
      setStatus({
        type: "error",
        message: errorMessage(error, "無法取得 網站嵌入金鑰列表"),
      });
      return false;
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    void (async () => {
      try {
        const payload = await fetchProjects();
        setProjects(payload.projects);
      } catch {
        setProjects([]);
      }
    })();
  }, []);

  function projectLabel(projectId: string): string {
    return (
      projects.find((project) => project.project_id === projectId)?.label
      ?? projectId
    );
  }

  function openCreateModal() {
    setFormError(null);
    setEditingKeyId(null);
    setForm({ ...EMPTY_FORM, projectId: projects[0]?.project_id ?? "default" });
    setModalOpen(true);
  }

  function openEditModal(key: EmbedKey) {
    setFormError(null);
    setEditingKeyId(key.key_id);
    setForm(formFromKey(key));
    setModalOpen(true);
  }

  function updateForm(changes: Partial<KeyFormState>): void {
    if (submitting) return;
    setForm((current) => ({ ...current, ...changes }));
  }

  async function runAction(
    action: () => Promise<unknown>,
    fallback: string,
  ): Promise<boolean> {
    try {
      await action();
      await reload();
      return true;
    } catch (error) {
      setStatus({ type: "error", message: errorMessage(error, fallback) });
      return false;
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    const origins = parseDelimitedList(form.origins);
    if (origins.length === 0) {
      setFormError("至少需要一個允許的來源網域。");
      // 訊息相同時 React 不會再次觸發 effect，仍需把焦點帶回提示。
      formErrorRef.current?.focus();
      return;
    }
    setSubmitting(true);
    setFormError(null);
    setStatus(null);

    const shared = {
      label: form.label.trim(),
      allowed_origins: origins,
      default_character_id: form.defaultCharacterId.trim(),
      allowed_character_ids: parseDelimitedList(form.allowedCharacterIds),
      default_persona_id: form.defaultPersonaId.trim(),
      default_tts_provider: form.defaultTtsProvider.trim(),
      default_tts_voice: form.defaultTtsVoice.trim(),
      rate_limit_per_minute: form.rateLimitPerMinute,
      daily_request_quota: form.dailyRequestQuota,
    };

    try {
      if (editingKeyId) {
        await updateEmbedKey(editingKeyId, shared);
      } else {
        await createEmbedKey({ ...shared, project_id: form.projectId });
      }
      // 保留原本的操作按鈕，讓儲存關閉後仍可還原焦點。
      const refreshed = await reload(false);
      setModalOpen(false);
      setEditingKeyId(null);
      // 金鑰已經存進去了，表單照樣關；清單沒刷新成功要講清楚，免得使用者以為沒存到又送一次。
      setStatus(refreshed
        ? {
          type: "success",
          message: editingKeyId ? "已更新 網站嵌入金鑰。" : "已建立 網站嵌入金鑰。",
        }
        : {
          type: "error",
          message: editingKeyId
            ? "已更新 網站嵌入金鑰，但清單刷新失敗，請重新整理頁面。"
            : "已建立 網站嵌入金鑰，但清單刷新失敗，請重新整理頁面。",
        });
    } catch (error) {
      setFormError(errorMessage(
        error,
        editingKeyId ? "更新 網站嵌入金鑰失敗" : "建立 網站嵌入金鑰失敗",
      ));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopy(keyId: string) {
    try {
      await navigator.clipboard?.writeText(keyId);
      setCopiedKeyId(keyId);
      window.setTimeout(() => setCopiedKeyId(null), 2000);
    } catch {
      setStatus({ type: "error", message: "複製金鑰失敗，請手動選取。" });
    }
  }

  return (
    <div className="page-scroll">
      <header className="section-header">
        <div className="page-heading">
          <h2 className="page-section-title">網站嵌入金鑰</h2>
          <p className="page-subtitle">
            放在外部網站上，讓訪客直接使用虛擬人，不用登入。每把金鑰綁一個專案，可以限制網域與每日用量。
          </p>
        </div>
        <button
          type="button"
          onClick={openCreateModal}
          className="btn btn-primary shrink-0"
        >
          建立金鑰
        </button>
      </header>

      <div className="page-body space-y-6">
        {status && (
          <StatusAlert
            type={status.type}
            message={status.message}
            onDismiss={() => setStatus(null)}
          />
        )}

        {loading && (
          <p className="text-sm text-content-muted">載入中…</p>
        )}
        {!loading && keys.length === 0 && (
          <p className="text-sm text-content-muted">
            尚未建立任何 網站嵌入金鑰。
          </p>
        )}
        {!loading && keys.length > 0 && (
          <div className="overflow-x-auto rounded-3xl border border-border bg-surface shadow-sm dark:bg-surface-sunken/40 dark:shadow-none">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wider text-content-subtle">
                <tr>
                  <th className="px-5 py-3">金鑰</th>
                  <th className="px-5 py-3">名稱</th>
                  <th className="px-5 py-3">專案</th>
                  <th className="px-5 py-3">來源網域</th>
                  <th className="px-5 py-3">限制</th>
                  <th className="px-5 py-3">今日請求</th>
                  <th className="px-5 py-3">狀態</th>
                  <th className="px-5 py-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.key_id} className="border-b border-border/60 last:border-0">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <code className="text-xs text-content">{key.key_id}</code>
                        <button
                          type="button"
                          aria-label={`複製 ${key.key_id}`}
                          onClick={() => void handleCopy(key.key_id)}
                          className="rounded-lg border border-border px-2 py-1 text-xs text-content-muted transition-all hover:text-content"
                        >
                          {copiedKeyId === key.key_id ? "已複製" : "複製"}
                        </button>
                      </div>
                    </td>
                    <td className="px-5 py-4 text-content">{key.label || "—"}</td>
                    <td className="px-5 py-4 text-content-muted">
                      {projectLabel(key.project_id)}
                    </td>
                    <td className="px-5 py-4 text-xs text-content-muted">
                      {key.allowed_origins.join("、")}
                    </td>
                    <td className="px-5 py-4 text-xs text-content-muted">
                      {key.rate_limit_per_minute}/分、{key.daily_request_quota}/日
                    </td>
                    <td className="px-5 py-4 text-content">{key.requests_today}</td>
                    <td className="px-5 py-4">
                      <span
                        className={
                          key.disabled
                            ? "text-xs text-content-subtle"
                            : "text-xs text-emerald-600 dark:text-emerald-400"
                        }
                      >
                        {key.disabled ? "已停用" : "啟用中"}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => openEditModal(key)}
                          className="rounded-lg border border-border px-3 py-1 text-xs text-content-muted transition-all hover:text-content"
                        >
                          編輯
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void runAction(
                              () => setEmbedKeyDisabled(key.key_id, !key.disabled),
                              "切換金鑰狀態失敗",
                            )
                          }
                          className="rounded-lg border border-border px-3 py-1 text-xs text-content-muted transition-all hover:text-content"
                        >
                          {key.disabled ? "啟用" : "停用"}
                        </button>
                        <button
                          type="button"
                          aria-label={`刪除 ${key.key_id}`}
                          onClick={() => setDeleteTarget(key)}
                          className="rounded-lg border border-rose-300 px-3 py-1 text-xs text-rose-600 transition-all hover:bg-rose-50 dark:border-rose-500/30 dark:text-rose-400 dark:hover:bg-rose-500/10"
                        >
                          刪除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modalOpen && (
        <dialog
          ref={dialogRef}
          {...{ closedby: submitting ? "none" : "closerequest" }}
          aria-labelledby="embed-key-form-title"
          onCancel={(event) => {
            event.preventDefault();
            if (!submitting) setModalOpen(false);
          }}
          onClose={() => {
            const dialog = dialogRef.current;
            if (submitting && dialog?.isConnected) {
              // 不支援 closedby 或瀏覽器強制關閉時，保留這份送出中的表單。
              if (!dialog.open) {
                if (typeof dialog.showModal === "function") {
                  dialog.showModal();
                } else {
                  dialog.setAttribute("open", "");
                }
              }
            } else {
              setModalOpen(false);
            }
          }}
          className="m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto overscroll-contain rounded-3xl border border-border bg-surface p-6 text-content shadow-lg backdrop:overscroll-contain backdrop:bg-black/40 dark:bg-surface-sunken"
        >
          <form
            onSubmit={handleSubmit}
            aria-busy={submitting}
            aria-label={editingKeyId ? "編輯 網站嵌入金鑰" : "建立 網站嵌入金鑰"}
          >
            <h3 id="embed-key-form-title" className="card-title">
              {editingKeyId ? "編輯 網站嵌入金鑰" : "建立 網站嵌入金鑰"}
            </h3>

            <fieldset disabled={submitting} className="min-w-0">
              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <div>
                  <label className={labelClass} htmlFor="embed-key-label">
                    名稱
                  </label>
                  <input
                    id="embed-key-label"
                    type="text"
                    value={form.label}
                    onChange={(event) => updateForm({ label: event.target.value })}
                    placeholder="例：合作夥伴官網"
                    className={inputClass}
                  />
                </div>

                <div>
                  <label className={labelClass} htmlFor="embed-key-project">
                    專案
                  </label>
                  {editingKeyId ? (
                    <p className="px-1 py-3 text-sm text-content-muted">
                      {projectLabel(form.projectId)}（建立後不可變更）
                    </p>
                  ) : (
                    <Select
                      ariaLabel="專案"
                      disabled={submitting}
                      value={form.projectId}
                      onChange={(value) => updateForm({ projectId: value })}
                      options={projects.map((project) => ({
                        value: project.project_id,
                        label: project.label,
                      }))}
                      placeholder="選擇專案"
                    />
                  )}
                </div>
              </div>

              <div className="mt-4">
                <label className={labelClass} htmlFor="embed-key-origins">
                  允許的來源網域（每行一個，需含 scheme，不可使用 *）
                </label>
                <textarea
                  id="embed-key-origins"
                  value={form.origins}
                  onChange={(event) => updateForm({ origins: event.target.value })}
                  rows={3}
                  placeholder="https://partner.example"
                  className={inputClass}
                />
              </div>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div>
                  <label className={labelClass} htmlFor="embed-key-character">
                    預設角色
                  </label>
                  <input
                    id="embed-key-character"
                    type="text"
                    value={form.defaultCharacterId}
                    onChange={(event) => updateForm({
                      defaultCharacterId: event.target.value,
                    })}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor="embed-key-extra-characters">
                    額外允許角色（逗號分隔）
                  </label>
                  <input
                    id="embed-key-extra-characters"
                    type="text"
                    value={form.allowedCharacterIds}
                    onChange={(event) => updateForm({
                      allowedCharacterIds: event.target.value,
                    })}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor="embed-key-persona">
                    預設 Persona
                  </label>
                  <input
                    id="embed-key-persona"
                    type="text"
                    value={form.defaultPersonaId}
                    onChange={(event) => updateForm({
                      defaultPersonaId: event.target.value,
                    })}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor="embed-key-provider">
                    預設 TTS Provider
                  </label>
                  <input
                    id="embed-key-provider"
                    type="text"
                    value={form.defaultTtsProvider}
                    onChange={(event) => updateForm({
                      defaultTtsProvider: event.target.value,
                    })}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor="embed-key-voice">
                    預設語音
                  </label>
                  <input
                    id="embed-key-voice"
                    type="text"
                    value={form.defaultTtsVoice}
                    onChange={(event) => updateForm({
                      defaultTtsVoice: event.target.value,
                    })}
                    className={inputClass}
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className={labelClass} htmlFor="embed-key-rate">
                      每分鐘上限
                    </label>
                    <input
                      id="embed-key-rate"
                      type="number"
                      min={1}
                      value={form.rateLimitPerMinute}
                      onChange={(event) => updateForm({
                        rateLimitPerMinute: Number(event.target.value),
                      })}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className={labelClass} htmlFor="embed-key-quota">
                      每日上限
                    </label>
                    <input
                      id="embed-key-quota"
                      type="number"
                      min={1}
                      value={form.dailyRequestQuota}
                      onChange={(event) => updateForm({
                        dailyRequestQuota: Number(event.target.value),
                      })}
                      className={inputClass}
                    />
                  </div>
                </div>
              </div>

            </fieldset>

            {formError && (
              <p
                ref={formErrorRef}
                role="alert"
                tabIndex={-1}
                className="mt-4 rounded-xl border border-danger/20 bg-danger/10 p-4 text-sm text-danger"
              >
                {formError}
              </p>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                disabled={submitting}
                onClick={() => setModalOpen(false)}
                className="rounded-xl border border-border px-4 py-2 text-sm text-content-muted transition-all hover:text-content disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white transition-all hover:bg-primary/90 disabled:opacity-50"
              >
                {submitting
                  ? (editingKeyId ? "儲存中…" : "建立中…")
                  : (editingKeyId ? "儲存" : "建立")}
              </button>
            </div>
          </form>
        </dialog>
      )}

      <ConfirmModal
        open={deleteTarget !== null}
        title="刪除 網站嵌入金鑰"
        message={
          deleteTarget
            ? `刪除後使用 ${deleteTarget.key_id} 的網站會立即失效，且無法復原。`
            : ""
        }
        confirmLabel="刪除"
        danger
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          const target = deleteTarget;
          setDeleteTarget(null);
          if (target) {
            void runAction(
              () => deleteEmbedKey(target.key_id),
              "刪除 網站嵌入金鑰失敗",
            );
          }
        }}
      />
    </div>
  );
}

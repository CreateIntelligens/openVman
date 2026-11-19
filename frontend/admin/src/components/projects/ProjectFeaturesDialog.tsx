import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import {
  fetchProjectKnowledgeSettings,
  saveProjectFeatures,
  type ProjectFeatures,
} from "../../api/knowledge";
import { errorMessage } from "../../utils/errorMessage";
import StatusAlert from "../StatusAlert";

const features = [
  { field: "memory_enabled", label: "記憶", description: "記住過去對話，回答時參考。" },
  { field: "graph_enabled", label: "知識圖譜擴展", description: "用知識圖譜找出更多相關文件，回答時一起參考。" },
] as const;

interface ProjectFeaturesDialogProps {
  projectId: string;
  projectLabel: string;
  onClose: () => void;
  onSaved: () => void;
}

export default function ProjectFeaturesDialog({ projectId, projectLabel, onClose, onSaved }: ProjectFeaturesDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [settings, setSettings] = useState<ProjectFeatures | null>(null);
  const [draft, setDraft] = useState<ProjectFeatures | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement;
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");

    return () => {
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchProjectKnowledgeSettings(projectId)
      .then(({ memory_enabled, graph_enabled }) => {
        if (!active) return;
        if (typeof memory_enabled !== "boolean" || typeof graph_enabled !== "boolean") {
          throw new Error("目前無法讀取回答功能設定。");
        }
        const values = { memory_enabled, graph_enabled };
        setSettings(values);
        setDraft(values);
      })
      .catch((reason) => {
        if (active) setError(errorMessage(reason, "無法載入回答功能設定。"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [projectId, loadAttempt]);

  const changes: Partial<ProjectFeatures> = {};
  if (settings && draft) {
    for (const { field } of features) {
      if (settings[field] !== draft[field]) changes[field] = draft[field];
    }
  }
  const canSave = !loading && !saving && Object.keys(changes).length > 0;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      await saveProjectFeatures(projectId, changes);
      onSaved();
    } catch (reason) {
      setError(errorMessage(reason, "無法儲存回答功能設定。"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-md rounded-xl border border-border bg-surface-overlay p-6 text-content shadow-2xl"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!saving) onClose();
      }}
    >
      <h2 id={titleId} className="card-title">回答功能：{projectLabel}</h2>
      <form className="mt-4 space-y-4" onSubmit={submit}>
        {error && <StatusAlert type="error" message={error} />}
        {loading && <p role="status" className="text-sm text-content-muted">載入中…</p>}
        {!loading && draft && features.map(({ field, label, description }) => (
          <div key={field} className="flex items-center justify-between gap-4 rounded-lg border border-border bg-surface-sunken p-3">
            <div>
              <p id={`${titleId}-${field}`} className="text-sm font-medium">{label}</p>
              <p id={`${titleId}-${field}-help`} className="mt-1 text-xs text-content-muted">{description}</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={draft[field]}
              aria-labelledby={`${titleId}-${field}`}
              aria-describedby={`${titleId}-${field}-help`}
              disabled={saving}
              onClick={() => setDraft({ ...draft, [field]: !draft[field] })}
              className={`relative h-6 w-11 shrink-0 rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-50 ${
                draft[field] ? "bg-primary" : "bg-border-strong"
              }`}
            >
              <span
                aria-hidden="true"
                className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-surface shadow ${
                  draft[field] ? "translate-x-5" : "translate-x-0"
                }`}
              />
            </button>
          </div>
        ))}
        <div className="flex flex-wrap justify-end gap-3">
          {!loading && !draft && (
            <button className="btn btn-ghost" type="button" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>
              重新載入
            </button>
          )}
          <button className="btn btn-ghost" type="button" disabled={saving} onClick={onClose}>取消</button>
          <button className="btn btn-primary" type="submit" disabled={!canSave}>{saving ? "儲存中…" : "儲存"}</button>
        </div>
      </form>
    </dialog>
  );
}

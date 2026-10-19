import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  deleteProjectGeminiCredential,
  fetchProjectGeminiCredential,
  saveProjectGeminiCredential,
  type ProjectGeminiCredential,
} from "../../api/projects";
import { useAuth } from "../../context/AuthContext";
import { useModalDismiss } from "../useModalDismiss";

interface ProjectGeminiCredentialDialogProps {
  projectId: string;
  projectLabel: string;
  onClose: () => void;
}

export default function ProjectGeminiCredentialDialog(props: ProjectGeminiCredentialDialogProps) {
  const { account } = useAuth();
  return account?.role === "root" ? <RootCredentialDialog key={props.projectId} {...props} /> : null;
}

function RootCredentialDialog({ projectId, projectLabel, onClose }: ProjectGeminiCredentialDialogProps) {
  const [credential, setCredential] = useState<ProjectGeminiCredential | null>(null);
  const [label, setLabel] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const keyRef = useRef<HTMLInputElement>(null);

  function clearKey() {
    if (keyRef.current) keyRef.current.value = "";
    setHasKey(false);
  }

  function close() {
    if (saving) return;
    clearKey();
    onClose();
  }

  const dismiss = useModalDismiss(close, !saving);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchProjectGeminiCredential(projectId)
      .then((metadata) => {
        if (!active) return;
        setCredential(metadata);
        setLabel(metadata.label ?? "");
      })
      .catch(() => {
        if (active) setError("無法載入 Gemini 金鑰設定，請重試。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId, loadAttempt]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || loading || !credential) return;
    const apiKey = keyRef.current?.value.trim() ?? "";
    if (!label.trim() || !apiKey || apiKey.length > 4096) {
      setError("請輸入金鑰名稱及有效的 Gemini API key。");
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const metadata = await saveProjectGeminiCredential(projectId, { label: label.trim(), api_key: apiKey });
      clearKey();
      setCredential(metadata);
      setLabel(metadata.label ?? "");
      setSuccess(metadata.runtime_refreshed === false
        ? "已儲存專案專屬金鑰，但執行中服務尚未更新，請聯絡維運人員。"
        : "已儲存專案專屬金鑰。");
    } catch {
      // 驗證或上游錯誤可能含請求內容，金鑰表單不顯示原始錯誤。
      setError("儲存失敗，請確認設定後重試。");
    } finally {
      setSaving(false);
    }
  }

  async function useSharedKey() {
    if (saving || loading || credential?.source !== "project") return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const metadata = await deleteProjectGeminiCredential(projectId);
      clearKey();
      setCredential(metadata);
      setLabel(metadata.label ?? "");
      setSuccess(metadata.runtime_refreshed === false
        ? "已移除專屬金鑰，但執行中服務尚未更新，請聯絡維運人員。"
        : "已改用共用金鑰。");
    } catch {
      setError("改用共用金鑰失敗，請重試。");
    } finally {
      setSaving(false);
    }
  }

  const busy = loading || saving;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="presentation" {...dismiss}>
      <section
        className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-xl border border-border bg-surface-overlay p-6 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-gemini-title"
      >
        <h2 id="project-gemini-title" className="card-title">Gemini 金鑰：{projectLabel}</h2>
        <p className="mt-2 text-sm leading-6 text-content-muted">
          僅 ROOT 可管理。綁定專屬金鑰可由此專案自己的 Google 專案分帳；未綁定時使用共用金鑰。
          專屬金鑰失效時會回報錯誤，不會自動改用共用金鑰。
        </p>

        {error && <p role="alert" className="mt-4 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{error}</p>}
        {success && <p role="status" className="mt-4 rounded-md border border-success/30 bg-success/10 px-4 py-3 text-sm text-success">{success}</p>}

        {loading ? <p className="mt-5 text-sm text-content-muted">載入中…</p> : credential ? (
          <div className="mt-5 rounded-lg border border-border bg-surface-sunken p-4 text-sm">
            <p className="font-medium text-content">目前使用：{credential.source === "project" ? "專案專屬金鑰" : "共用金鑰"}</p>
            {credential.source === "project" && (
              <dl className="mt-2 space-y-1 text-content-muted">
                <div className="flex flex-wrap gap-x-2"><dt>名稱</dt><dd className="break-all">{credential.label}</dd></div>
                <div className="flex flex-wrap gap-x-2"><dt>金鑰</dt><dd className="break-all font-mono">{credential.masked}</dd></div>
              </dl>
            )}
            {!credential.configured && <p className="mt-2 text-content-muted">目前尚未設定可用的共用金鑰，請綁定專屬金鑰或聯絡維運人員。</p>}
          </div>
        ) : <button type="button" className="btn btn-ghost mt-4" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>重新載入</button>}

        {credential && !loading && (
          <form className="mt-5 space-y-4" onSubmit={submit}>
            <label className="block text-sm font-medium text-content">
              金鑰名稱
              <input className="input mt-2" value={label} onChange={(event) => setLabel(event.target.value)} disabled={busy} required maxLength={128} autoComplete="off" placeholder="例：慧誠醫院 Google 專案" />
            </label>
            <label className="block text-sm font-medium text-content">
              {credential.source === "project" ? "新的 Gemini API key" : "Gemini API key"}
              <input
                ref={keyRef}
                className="input mt-2"
                type="password"
                onChange={(event) => setHasKey(Boolean(event.target.value.trim()))}
                disabled={busy}
                required
                maxLength={4096}
                autoComplete="new-password"
                spellCheck={false}
                aria-describedby="project-gemini-key-help"
              />
            </label>
            <p id="project-gemini-key-help" className="text-xs leading-5 text-content-muted">原金鑰不會回填；儲存成功或關閉視窗後，輸入內容會清除。</p>
            <div className="flex flex-wrap justify-end gap-3">
              <button className="btn btn-primary" type="submit" disabled={busy || !label.trim() || !hasKey}>
                {saving ? "處理中…" : credential.source === "project" ? "更換專屬金鑰" : "儲存專屬金鑰"}
              </button>
            </div>
          </form>
        )}

        <div className="mt-5 flex flex-wrap justify-end gap-3 border-t border-border pt-4">
          {credential?.source === "project" && <button className="btn btn-ghost" type="button" onClick={() => void useSharedKey()} disabled={busy}>改用共用金鑰</button>}
          <button className="btn btn-ghost" type="button" onClick={close} disabled={saving}>關閉</button>
        </div>
      </section>
    </div>
  );
}

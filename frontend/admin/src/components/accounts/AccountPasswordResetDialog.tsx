import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  resetAccountPassword,
  type Account,
} from "../../api/auth";
import { useModalDismiss } from "../useModalDismiss";
import { errorMessage } from "../../utils/errorMessage";

interface AccountPasswordResetDialogProps {
  account: Account;
  onClose: () => void;
  onSaved: (account: Account) => void;
}

export default function AccountPasswordResetDialog({
  account,
  onClose,
  onSaved,
}: AccountPasswordResetDialogProps) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const dismiss = useModalDismiss(() => {
    if (!saving) onClose();
  });

  useEffect(() => {
    passwordRef.current?.focus();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirmation) {
      setError("兩次輸入的密碼不一致");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const updated = await resetAccountPassword(account.id, password);
      setPassword("");
      setConfirmation("");
      onSaved(updated);
    } catch (reason) {
      setError(errorMessage(reason, "重設密碼失敗"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      {...dismiss}
    >
      <section
        className="w-full max-w-md rounded-xl border border-border bg-surface-overlay p-6 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="password-reset-title"
      >
        <h2 id="password-reset-title" className="card-title">
          重設 {account.username} 的密碼
        </h2>
        <p className="mt-2 text-sm leading-6 text-content-muted">
          請設定新密碼。系統無法讀取或顯示原密碼，成功後會立即撤銷此帳號的既有登入階段。
        </p>

        {error && (
          <div
            className="mt-4 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"
            role="alert"
          >
            {error}
          </div>
        )}

        <form className="mt-5 space-y-4" onSubmit={submit}>
          <label className="block text-sm font-medium">
            新密碼
            <input
              ref={passwordRef}
              className="input mt-2"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={8}
              maxLength={72}
              autoComplete="new-password"
              disabled={saving}
              required
            />
          </label>
          <label className="block text-sm font-medium">
            再次輸入新密碼
            <input
              className="input mt-2"
              type="password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              minLength={8}
              maxLength={72}
              autoComplete="new-password"
              disabled={saving}
              required
            />
          </label>
          <div className="flex flex-wrap justify-end gap-3 pt-2">
            <button
              className="btn btn-ghost"
              type="button"
              onClick={onClose}
              disabled={saving}
            >
              取消
            </button>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={saving || !password || !confirmation}
            >
              {saving ? "重設中…" : "確認重設"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

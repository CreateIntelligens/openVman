import { useState, type FormEvent } from "react";

import {
  updateAccountRole,
  type Account,
  type AssignableAccountRole,
} from "../../api/auth";
import { useModalDismiss } from "../useModalDismiss";
import { errorMessage } from "../../utils/errorMessage";
import AccountAccessFields, {
  useAccountAccessForm,
} from "./AccountAccessFields";

interface AccountRoleDialogProps {
  account: Account;
  onClose: () => void;
  onSaved: (account: Account) => void;
}

const ROLE_LABELS: Record<AssignableAccountRole, string> = {
  admin: "管理員",
  user: "一般使用者",
};

const ROLE_EFFECTS: Record<AssignableAccountRole, string> = {
  admin: "可使用所有已登錄資源，並管理一般與臨時帳號；原有一般使用者授權將不再生效。",
  user: "資源存取改為僅限下方所選的授權範圍。",
};

export default function AccountRoleDialog({
  account,
  onClose,
  onSaved,
}: AccountRoleDialogProps) {
  // 可指派的角色由型別驅動，新增角色時選單自動跟上（ROOT 不可指派）。
  const assignableRoles: AssignableAccountRole[] = ["admin", "user"];
  const [nextRole, setNextRole] = useState<AssignableAccountRole>(
    account.role === "admin" ? "user" : "admin",
  );
  const demoting = nextRole === "user";
  const unchanged = nextRole === account.role;
  const accessForm = useAccountAccessForm(
    `role-change-${account.id}`,
    account.grants && account.defaults
      ? {
        grants: account.grants,
        defaults: account.defaults,
        admin_portal_access: account.admin_portal_access ?? false,
      }
      : undefined,
    // 只有降級才會顯示授權欄位，提升為管理員時不必抓選項。
    demoting,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dismiss = useModalDismiss(() => {
    if (!saving) onClose();
  });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (demoting && !accessForm.complete) {
      setError("降級為一般使用者前，必須設定完整的資源權限與預設值。");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const updated = await updateAccountRole(account.id, {
        role: nextRole,
        ...(demoting ? { access: accessForm.access } : {}),
      });
      onSaved(updated);
    } catch (reason) {
      setError(errorMessage(reason, "變更角色失敗"));
    } finally {
      setSaving(false);
    }
  }

  const displayedError = error ?? (demoting ? accessForm.error : null);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      {...dismiss}
    >
      <section
        className="max-h-[90dvh] w-full max-w-3xl overflow-y-auto rounded-xl border border-border bg-surface-overlay shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="role-change-title"
      >
        <header className="border-b border-border px-6 py-5">
          <h2 id="role-change-title" className="card-title">
            變更角色
          </h2>
          <p className="mt-2 text-sm leading-6 text-content-muted">
            {account.username} 目前是{ROLE_LABELS[account.role as AssignableAccountRole]
              ?? account.role}。
          </p>
        </header>

        <div className="border-b border-border px-6 py-5">
          <label className="block text-sm font-medium">
            變更為
            <select
              className="input mt-2"
              value={nextRole}
              onChange={(event) => setNextRole(
                event.target.value as AssignableAccountRole,
              )}
              disabled={saving}
            >
              {assignableRoles.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                  {role === account.role ? "（目前角色）" : ""}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-2 text-sm leading-6 text-content-muted">
            {unchanged
              ? "與目前角色相同，請選擇其他角色。"
              : ROLE_EFFECTS[nextRole]}
          </p>
        </div>

        <form onSubmit={submit}>
          {displayedError && (
            <div
              className="mx-6 mt-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"
              role="alert"
            >
              {displayedError}
            </div>
          )}

          {demoting && (
            <div className="mt-5">
              <AccountAccessFields form={accessForm} />
            </div>
          )}

          <div className="flex flex-wrap justify-end gap-3 border-t border-border bg-surface-sunken px-6 py-4">
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
              disabled={
                saving
                || unchanged
                || (demoting && (accessForm.loading || !accessForm.complete))
              }
            >
              {saving ? "變更中…" : "確認變更角色"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

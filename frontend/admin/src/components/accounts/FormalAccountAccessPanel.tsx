import { useState } from "react";

import {
  updateAccountAccess,
  type Account,
  type AccountAccessInput,
} from "../../api/auth";
import AccountAccessFields, {
  useAccountAccessForm,
} from "./AccountAccessFields";

interface FormalAccountAccessPanelProps {
  account: Account;
  onSaved: (account: Account) => void;
  onCancel: () => void;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function FormalAccountAccessPanel({
  account,
  onSaved,
  onCancel,
}: FormalAccountAccessPanelProps) {
  const initialAccess: AccountAccessInput | undefined = (
    account.grants && account.defaults
      ? { grants: account.grants, defaults: account.defaults }
      : undefined
  );
  const accessForm = useAccountAccessForm(account.id, initialAccess);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!accessForm.complete) {
      setError("每一類都至少要選一項授權資源，並指定預設值。");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      onSaved(await updateAccountAccess(account.id, accessForm.access));
    } catch (reason) {
      setError(messageFrom(reason, "儲存資源權限失敗"));
    } finally {
      setSaving(false);
    }
  }

  const displayedError = error ?? accessForm.error;

  return (
    <section
      className="mt-4 border-t border-border pt-4"
      aria-label={`${account.username} 的資源權限`}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold">可用資源</h3>
          <p className="mt-1 text-xs text-content-muted">
            此帳號只能讀取勾選項目與自己建立的私有資源；儲存後立即生效。
          </p>
        </div>
        <button className="btn btn-ghost self-start" type="button" onClick={onCancel}>
          收合
        </button>
      </div>

      {displayedError && (
        <div
          className="mt-4 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"
          role="alert"
        >
          {displayedError}
        </div>
      )}

      <div className="mt-4">
        <AccountAccessFields form={accessForm} />
      </div>

      <div className="mt-4 flex justify-end gap-2">
        <button
          className="btn btn-ghost"
          type="button"
          onClick={onCancel}
          disabled={saving}
        >
          取消
        </button>
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => void save()}
          disabled={accessForm.loading || saving || !accessForm.complete}
        >
          {saving ? "儲存中…" : "儲存權限"}
        </button>
      </div>
    </section>
  );
}

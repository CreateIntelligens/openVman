import { useEffect, useRef, useState } from "react";

import {
  isAtLeastAdmin,
  updateAccountAccess,
  type Account,
  type AccountAccessInput,
} from "../../api/auth";
import { useUnsavedChanges } from "../../context/NavigationGuardContext";
import AccountAccessFields, {
  useAccountAccessForm,
  withProjectPermissions,
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
  const canSetProjectWrites = account.role === "user";
  const flags = {
    admin_portal_access: account.admin_portal_access ?? false,
    kiosk: account.kiosk ?? false,
    // 管理員回來的是生效值（一律為真）；降成一般帳號時不能因此默默開放。
    ai_cleanup_access: isAtLeastAdmin(account.role) ? false : (account.ai_cleanup_access ?? false),
    web_search_access: account.web_search_access ?? false,
  };
  const initialAccess: Partial<AccountAccessInput> = {
    ...flags,
    ...(account.grants && { grants: account.grants }),
    ...(account.defaults && { defaults: account.defaults }),
  };
  const accessForm = useAccountAccessForm(
    account.id,
    canSetProjectWrites && account.grants && account.defaults
      ? withProjectPermissions(
        { ...flags, grants: account.grants, defaults: account.defaults },
        account.vendor_name,
        Boolean(!account.vendor_name && account.admin_portal_access),
      )
      : initialAccess,
    true,
    account.vendor_name,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 讀到資料後的快照；跟現在的表單不同就是「尚未儲存」，切帳號或離開頁面前會先問。
  const snapshot = useRef<{ resources: string; webSearch: boolean } | null>(null);
  const { web_search_access: webSearch = false, ...resourceAccess } = accessForm.access;
  const serialized = JSON.stringify(resourceAccess);
  useEffect(() => {
    if (!accessForm.loading && snapshot.current === null) {
      snapshot.current = { resources: serialized, webSearch };
    }
  }, [accessForm.loading, serialized, webSearch]);
  const accessDirty = snapshot.current !== null && serialized !== snapshot.current.resources;
  const webSearchDirty = snapshot.current !== null && webSearch !== snapshot.current.webSearch;
  const webSearchOnly = webSearchDirty && !accessDirty;
  const dirty = accessDirty || webSearchDirty;
  useUnsavedChanges(`account-access:${account.id}`, dirty, `${account.username} 的資源權限`);

  async function save() {
    if (!webSearchOnly && !accessForm.complete) {
      setError("每一類都至少要選一項授權資源，並指定預設值。");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const access = canSetProjectWrites
        ? withProjectPermissions(resourceAccess, account.vendor_name)
        : resourceAccess;
      const saved = await updateAccountAccess(account.id, webSearchOnly
        ? { web_search_access: webSearch }
        : { ...access, ...(webSearchDirty && { web_search_access: webSearch }) });
      snapshot.current = { resources: serialized, webSearch };
      onSaved(saved);
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
          <h3 className="card-title">可用資源</h3>
          <p className="mt-1 text-xs text-content-muted">
            {isAtLeastAdmin(account.role)
              ? "管理員看得到全部資源；這裡只設定登入預設值與可分配的專案專屬資源。儲存後立即生效。"
              : "此帳號只能讀取勾選項目與自己建立的私有資源；儲存後立即生效。"}
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
        <AccountAccessFields
          form={accessForm}
          role={account.role}
          allowProjectWrites={canSetProjectWrites}
          showWebSearchAccess
          submitting={saving}
        />
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
          disabled={accessForm.loading || saving || (!accessForm.complete && !webSearchOnly)}
        >
          {saving ? "儲存中…" : "儲存權限"}
        </button>
      </div>
    </section>
  );
}

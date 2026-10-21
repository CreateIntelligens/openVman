import { useEffect, useRef, useState } from "react";

import {
  fetchAccountAccessOptions,
  fetchAdminScope,
  updateAdminScope,
  type Account,
  type AccountAccessOptions,
  type AdminScopeResources,
} from "../../api/auth";
import { useAuth } from "../../context/AuthContext";
import { useUnsavedChanges } from "../../context/NavigationGuardContext";
import AdminScopeFields, { EMPTY_SCOPE_RESOURCES } from "./AdminScopeFields";




interface AdminScopePanelProps {
  account: Account;
  onCancel: () => void;
  onSaved: () => void;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}


export default function AdminScopePanel({
  account,
  onCancel,
  onSaved,
}: AdminScopePanelProps) {
  const { account: currentAccount } = useAuth();
  // 只有 ROOT 給得出「不設限」。受限 admin 取消勾選的話 API 必回 422，
  // 與其讓他存檔後才撞牆，不如直接停用這個選項。
  const canUnrestrict = currentAccount?.role === "root";
  const [options, setOptions] = useState<AccountAccessOptions | null>(null);
  const [scoped, setScoped] = useState(false);
  const [selection, setSelection] = useState<AdminScopeResources>(EMPTY_SCOPE_RESOURCES);
  const [loading, setLoading] = useState(true);
  // 讀到目前的上限才准儲存：讀失敗時表單裡是預設的「不設限」，ROOT 一按儲存
  // 就會把管理員的限制整個解掉。
  const [loaded, setLoaded] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const snapshot = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoaded(false);
    setError(null);
    Promise.all([fetchAccountAccessOptions(), fetchAdminScope(account.id)])
      .then(([fetchedOptions, scope]) => {
        if (cancelled) return;
        setOptions(fetchedOptions);
        const loadedSelection = { ...EMPTY_SCOPE_RESOURCES, ...scope.resources };
        snapshot.current = JSON.stringify({ scoped: scope.scoped, resources: loadedSelection });
        setScoped(scope.scoped);
        setSelection(loadedSelection);
        setLoaded(true);
      })
      .catch((reason) => {
        if (!cancelled) setError(messageFrom(reason, "載入資源上限失敗"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [account.id, loadAttempt]);

  // 跟讀到的上限不同就是「尚未儲存」：收合面板、切帳號或離開頁面前會先問。
  const dirty = loaded && snapshot.current !== JSON.stringify({ scoped, resources: selection });
  useUnsavedChanges(`admin-scope:${account.id}`, dirty, `${account.username} 的資源上限`);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await updateAdminScope(account.id, {
        scoped,
        resources: scoped ? selection : EMPTY_SCOPE_RESOURCES,
      });
      onSaved();
    } catch (reason) {
      setError(messageFrom(reason, "儲存資源上限失敗"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className="mt-4 border-t border-border pt-4"
      aria-label={`${account.username} 的資源上限`}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="card-title">資源上限</h3>
          <p className="mt-1 text-xs text-content-muted">
            限制這位管理員看得到、也發得出去的資源。他再開帳號時，只能從這份清單裡分配。
          </p>
        </div>
        <button className="btn btn-ghost self-start" type="button" onClick={onCancel}>
          收合
        </button>
      </div>

      {error && (
        <div
          className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"
          role="alert"
        >
          <span>{error}</span>
          {!loaded && (
            <button
              className="btn btn-ghost px-2 py-1 text-xs"
              type="button"
              onClick={() => setLoadAttempt((attempt) => attempt + 1)}
              disabled={loading}
            >
              重新讀取
            </button>
          )}
        </div>
      )}

      <AdminScopeFields
        options={options}
        loading={loading}
        scoped={scoped}
        canUnrestrict={canUnrestrict}
        selection={selection}
        onScopedChange={setScoped}
        onSelectionChange={setSelection}
      />

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
          disabled={!loaded || loading || saving}
        >
          {saving ? "儲存中…" : "儲存上限"}
        </button>
      </div>
    </section>
  );
}

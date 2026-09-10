import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  createAccount,
  deleteAccount,
  listAccounts,
  revokeAccountSessions,
  setAccountDisabled,
  type Account,
  type AssignableAccountRole,
} from "../api/auth";
import AccountPasswordResetDialog from "../components/accounts/AccountPasswordResetDialog";
import AccountRoleDialog from "../components/accounts/AccountRoleDialog";
import AdminScopePanel from "../components/accounts/AdminScopePanel";
import FormalAccountAccessPanel from "../components/accounts/FormalAccountAccessPanel";
import TemporaryBatchPanel from "../components/accounts/TemporaryBatchPanel";
import { useAuth } from "../context/AuthContext";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function ownedResourceCount(account: Account): number {
  return Object.values(account.resource_counts ?? {}).reduce(
    (total, count) => total + count,
    0,
  );
}

function grantedResourceCount(account: Account): number {
  if (!account.grants) return 0;
  return Object.values(account.grants).reduce(
    (total, resourceIds) => total + resourceIds.length,
    0,
  );
}

export default function Accounts() {
  const { account: currentAccount } = useAuth();
  const isRoot = currentAccount?.role === "root";
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AssignableAccountRole>("user");
  const [creationMode, setCreationMode] = useState<"formal" | "temporary">(
    "formal",
  );
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null);
  const [editingScopeAccountId, setEditingScopeAccountId] = useState<string | null>(null);
  const [roleChangeAccount, setRoleChangeAccount] = useState<Account | null>(
    null,
  );
  const [passwordResetAccount, setPasswordResetAccount] = useState<Account | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAccounts(await listAccounts());
    } catch (nextError) {
      setError(errorMessage(nextError, "無法取得帳號列表"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedUsername = username.trim();
    if (!trimmedUsername || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createAccount({
        username: trimmedUsername,
        password,
        role,
      });
      setUsername("");
      setPassword("");
      setRole("user");
      await reload();
      // 建立一般使用者時，建立後自動展開下方列表對應的「資源權限」面板，引導完成授權
      if (created.role === "user") {
        setEditingAccountId(created.id);
      }
    } catch (nextError) {
      setError(errorMessage(nextError, "建立帳號失敗"));
    } finally {
      setSubmitting(false);
    }
  }

  async function runAction(action: () => Promise<unknown>, fallback: string) {
    setError(null);
    try {
      await action();
      await reload();
    } catch (nextError) {
      setError(errorMessage(nextError, fallback));
    }
  }

  function replaceAccount(updated: Account) {
    setAccounts((current) => current.map((account) => (
      account.id === updated.id ? updated : account
    )));
  }

  return (
    <div className="page-scroll p-6 lg:p-8">
      <header className="page-header">
        <div>
          <h1 className="page-title">帳號管理</h1>
          <p className="page-subtitle">建立正式或臨時帳號，並可於下方列表中隨時調整資源權限。</p>
        </div>
      </header>

      {error && (
        <div className="mb-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      <nav className="mb-4 flex border-b border-border" aria-label="選擇帳號建立方式">
        <button
          className={`-mb-px flex-1 border-b-2 px-4 py-3 text-left sm:flex-none ${
            creationMode === "formal"
              ? "border-primary text-content"
              : "border-transparent text-content-muted hover:text-content"
          }`}
          type="button"
          aria-pressed={creationMode === "formal"}
          onClick={() => setCreationMode("formal")}
        >
          <span className="block text-sm font-semibold">正式帳號</span>
          <span className="mt-1 block text-xs">持續使用，可個別管理權限</span>
        </button>
        <button
          className={`-mb-px flex-1 border-b-2 px-4 py-3 text-left sm:flex-none ${
            creationMode === "temporary"
              ? "border-primary text-content"
              : "border-transparent text-content-muted hover:text-content"
          }`}
          type="button"
          aria-pressed={creationMode === "temporary"}
          onClick={() => setCreationMode("temporary")}
        >
          <span className="block text-sm font-semibold">臨時帳號</span>
          <span className="mt-1 block text-xs">每批 5 組，首次登入後 72 小時</span>
        </button>
      </nav>

      {creationMode === "formal" && (
        <>
        <section className="card mb-6 overflow-hidden">
          <header className="border-b border-border px-5 py-4">
            <h2 className="card-title">新增正式帳號</h2>
            <p className="mt-1 text-sm text-content-muted">
              建立一般使用者或管理員帳號；建立後可於下方列表個別指派或調整資源權限。
            </p>
          </header>
          <form onSubmit={handleCreate}>
            <div className="grid gap-4 px-5 py-5 md:grid-cols-[1fr_1fr_0.75fr]">
              <label className="text-sm font-medium">
                帳號
                <input
                  className="input mt-2"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="off"
                  disabled={submitting}
                  required
                />
              </label>
              <label className="text-sm font-medium">
                密碼
                <input
                  className="input mt-2"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  minLength={8}
                  maxLength={72}
                  autoComplete="new-password"
                  disabled={submitting}
                  required
                />
              </label>
              <label className="text-sm font-medium">
                角色
                <select
                  className="input mt-2"
                  value={role}
                  onChange={(event) => setRole(
                    event.target.value as AssignableAccountRole,
                  )}
                  disabled={submitting}
                >
                  <option value="user">一般使用者</option>
                  {isRoot && <option value="admin">管理員</option>}
                </select>
              </label>
            </div>

            <div className="flex flex-col gap-3 border-t border-border bg-surface-sunken px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-content-muted">
                {role === "user"
                  ? "建立一般使用者後，系統將自動於下方列表展開權限設定面板以供指派資源。"
                  : "管理員預設可存取全部資源，建立後亦可由 ROOT 限縮其資源上限。"}
              </p>
              <button
                className="btn btn-primary self-start sm:self-auto"
                type="submit"
                disabled={submitting || !username.trim() || !password}
              >
                {submitting ? "建立中…" : "建立正式帳號"}
              </button>
            </div>
          </form>
        </section>

        <section className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="card-title">正式帳號列表</h2>
            <button className="btn btn-ghost" type="button" onClick={() => void reload()} disabled={loading}>
              重新整理
            </button>
          </div>
          {loading ? (
            <div className="p-8 text-center text-sm text-content-muted" role="status">載入帳號中…</div>
          ) : (
            <div className="divide-y divide-border">
              {accounts.map((account) => {
                const isSelf = account.id === currentAccount?.id;
                const isFormal = (
                  account.kind ?? account.account_type ?? "formal"
                ) === "formal";
                const canManage = !isSelf && isFormal && (
                  isRoot
                    ? account.role !== "root"
                    : account.role === "user"
                );
                const resourceCount = ownedResourceCount(account);
                const grantCount = grantedResourceCount(account);
                // 管理員也能有自己的可用資源，但只有 ROOT 指定得了。
                const canEditAccess = canManage && (
                  account.role === "user" || (isRoot && account.role === "admin")
                );
                const editingAccess = editingAccountId === account.id;
                // 資源上限只有 ROOT 能設，且只對管理員有意義。
                const canEditScope = isRoot && !isSelf && isFormal
                  && account.role === "admin";
                const editingScope = editingScopeAccountId === account.id;
                return (
                  <article key={account.id} className="px-5 py-4">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{account.username}</span>
                          <span className="chip">
                            {account.role === "root" ? "ROOT" : account.role}
                          </span>
                          {canEditAccess && (
                            <>
                              <span className="chip">
                                {grantCount > 0
                                  ? `已授權 ${grantCount} 項`
                                  : "尚未授權"}
                              </span>
                              <span className="chip">
                                {account.admin_portal_access
                                  ? "可進管理後台"
                                  : "不可進管理後台"}
                              </span>
                            </>
                          )}
                          {isSelf && (
                            <span className="chip border-primary/30 text-primary">
                              目前帳號
                            </span>
                          )}
                          {account.disabled && (
                            <span className="chip border-danger/30 text-danger">
                              已停用
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-content-subtle">
                          建立於 {new Date(account.created_at).toLocaleString("zh-TW")}
                          {resourceCount > 0
                            ? ` · 私有資源 ${resourceCount} 項`
                            : ""}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {canEditAccess && (
                          <button
                            className={editingAccess
                              ? "btn btn-primary"
                              : "btn btn-ghost"}
                            type="button"
                            aria-expanded={editingAccess}
                            onClick={() => setEditingAccountId(
                              editingAccess ? null : account.id,
                            )}
                          >
                            資源權限
                          </button>
                        )}
                        {canEditScope && (
                          <button
                            className={editingScope
                              ? "btn btn-primary"
                              : "btn btn-ghost"}
                            type="button"
                            aria-expanded={editingScope}
                            onClick={() => setEditingScopeAccountId(
                              editingScope ? null : account.id,
                            )}
                          >
                            資源上限
                          </button>
                        )}
                        {isRoot && canManage && (
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => setRoleChangeAccount(account)}
                          >
                            變更角色
                          </button>
                        )}
                        {isRoot && canManage && (
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => setPasswordResetAccount(account)}
                          >
                            重設密碼
                          </button>
                        )}
                        {canManage && (
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => void runAction(
                              () => setAccountDisabled(account.id, !account.disabled),
                              account.disabled ? "啟用帳號失敗" : "停用帳號失敗",
                            )}
                          >
                            {account.disabled ? "啟用" : "停用"}
                          </button>
                        )}
                        {canManage && (
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => void runAction(
                              () => revokeAccountSessions(account.id),
                              "撤銷登入階段失敗",
                            )}
                          >
                            登出所有裝置
                          </button>
                        )}
                        {canManage && (
                          <button
                            className="btn btn-danger"
                            type="button"
                            disabled={!account.disabled || resourceCount > 0}
                            title={resourceCount > 0
                              ? "請先移除或轉移帳號擁有的私有資源"
                              : undefined}
                            onClick={() => {
                              if (!window.confirm(
                                `確定刪除帳號「${account.username}」？`,
                              )) return;
                              void runAction(
                                () => deleteAccount(account.id),
                                "刪除帳號失敗",
                              );
                            }}
                          >
                            刪除
                          </button>
                        )}
                      </div>
                    </div>
                    {editingScope && (
                      <AdminScopePanel
                        account={account}
                        onCancel={() => setEditingScopeAccountId(null)}
                        onSaved={() => setEditingScopeAccountId(null)}
                      />
                    )}
                    {editingAccess && (
                      <FormalAccountAccessPanel
                        account={account}
                        onCancel={() => setEditingAccountId(null)}
                        onSaved={(updated) => {
                          replaceAccount(updated);
                          setEditingAccountId(null);
                        }}
                      />
                    )}
                  </article>
                );
              })}
              {accounts.length === 0 && (
                <div className="p-8 text-center text-sm text-content-muted">尚無正式帳號資料</div>
              )}
            </div>
          )}
        </section>
        </>
      )}

      {creationMode === "temporary" && <TemporaryBatchPanel />}

      {roleChangeAccount && (
        <AccountRoleDialog
          account={roleChangeAccount}
          onClose={() => setRoleChangeAccount(null)}
          onSaved={(updated) => {
            replaceAccount(updated);
            setRoleChangeAccount(null);
          }}
        />
      )}

      {passwordResetAccount && (
        <AccountPasswordResetDialog
          account={passwordResetAccount}
          onClose={() => setPasswordResetAccount(null)}
          onSaved={(updated) => {
            replaceAccount(updated);
            setPasswordResetAccount(null);
          }}
        />
      )}
    </div>
  );
}

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
import AccountAccessFields, {
  useAccountAccessForm,
} from "../components/accounts/AccountAccessFields";
import AccountPasswordResetDialog from "../components/accounts/AccountPasswordResetDialog";
import AccountRoleDialog from "../components/accounts/AccountRoleDialog";
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
  const [roleChangeAccount, setRoleChangeAccount] = useState<Account | null>(
    null,
  );
  const [passwordResetAccount, setPasswordResetAccount] = useState<Account | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accessForm = useAccountAccessForm("formal-account-create");

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
    if (!username.trim() || !password) return;
    if (role === "user" && !accessForm.complete) {
      setError("一般使用者必須先選好各類資源授權與登入後預設值。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createAccount({
        username: username.trim(),
        password,
        role,
        ...(role === "user" ? { access: accessForm.access } : {}),
      });
      setUsername("");
      setPassword("");
      setRole("user");
      accessForm.reload();
      await reload();
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
          <p className="page-subtitle">先設定可用資源，再建立正式或臨時帳號；建立後仍可隨時調整。</p>
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
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold">新增正式帳號</h2>
              <span className="chip">1 帳號資料</span>
              <span className="chip">2 資源權限</span>
            </div>
            <p className="mt-1 text-sm text-content-muted">
              一般使用者會在建立當下取得所選權限，不需要再到帳號列表補設定。
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

            {role === "user" ? (
              <section className="border-t border-border" aria-labelledby="new-account-access-title">
                <div className="px-5 py-4">
                  <h3 id="new-account-access-title" className="font-semibold">資源權限</h3>
                  <p className="mt-1 text-xs text-content-muted">
                    每一類至少選一項；預設值只能從已授權的項目中指定。
                  </p>
                </div>
                {accessForm.error && (
                  <div className="mx-5 mb-4 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger" role="alert">
                    {accessForm.error}
                  </div>
                )}
                <AccountAccessFields form={accessForm} />
              </section>
            ) : (
              <div className="border-t border-border bg-surface-sunken px-5 py-4 text-sm text-content-muted">
                管理員可使用所有已登錄資源，因此不需要另外設定資源權限。
              </div>
            )}

            <div className="flex flex-col gap-3 border-t border-border bg-surface-sunken px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-content-muted">
                建立後可從下方帳號列表重新調整一般使用者的資源權限。
              </p>
              <button
                className="btn btn-primary self-start sm:self-auto"
                type="submit"
                disabled={
                  submitting
                  || (role === "user" && (accessForm.loading || !accessForm.complete))
                }
              >
                {submitting ? "建立中…" : "建立正式帳號"}
              </button>
            </div>
          </form>
        </section>

        <section className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-base font-semibold">正式帳號列表</h2>
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
                const canEditAccess = canManage && account.role === "user";
                const editingAccess = editingAccountId === account.id;
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
                            <span className="chip">
                              {grantCount > 0
                                ? `已授權 ${grantCount} 項`
                                : "尚未授權"}
                            </span>
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
                    {editingAccess && (
                      <FormalAccountAccessPanel
                        account={account}
                        onCancel={() => setEditingAccountId(null)}
                        onSaved={(updated) => {
                          setAccounts((current) => current.map((item) => (
                            item.id === updated.id ? updated : item
                          )));
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

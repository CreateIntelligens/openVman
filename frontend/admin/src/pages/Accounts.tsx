import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  createAccount,
  deleteAccount,
  listAccounts,
  revokeAccountSessions,
  setAccountDisabled,
  type Account,
  type AccountRole,
} from "../api/auth";
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

export default function Accounts() {
  const { account: currentAccount } = useAuth();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AccountRole>("user");
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
    if (!username.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      await createAccount({ username: username.trim(), password, role });
      setUsername("");
      setPassword("");
      setRole("user");
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

  return (
    <div className="page-scroll p-6 lg:p-8">
      <header className="page-header">
        <div>
          <h1 className="page-title">帳號管理</h1>
          <p className="page-subtitle">建立帳號並管理登入狀態；資源歸屬由後端強制隔離。</p>
        </div>
      </header>

      {error && (
        <div className="mb-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      <section className="card mb-6 p-5">
        <h2 className="text-base font-semibold">新增帳號</h2>
        <form className="mt-4 grid gap-4 md:grid-cols-[1fr_1fr_0.75fr_auto] md:items-end" onSubmit={handleCreate}>
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
              onChange={(event) => setRole(event.target.value as AccountRole)}
              disabled={submitting}
            >
              <option value="user">一般使用者</option>
              <option value="admin">管理員</option>
            </select>
          </label>
          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting ? "建立中…" : "建立帳號"}
          </button>
        </form>
      </section>

      <TemporaryBatchPanel />

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-base font-semibold">帳號列表</h2>
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
              const resourceCount = ownedResourceCount(account);
              return (
                <article key={account.id} className="flex flex-col gap-4 px-5 py-4 lg:flex-row lg:items-center">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{account.username}</span>
                      <span className="chip">{account.role}</span>
                      {account.kind === "temporary" && <span className="chip">臨時</span>}
                      {isSelf && <span className="chip border-primary/30 text-primary">目前帳號</span>}
                      {account.disabled && <span className="chip border-danger/30 text-danger">已停用</span>}
                    </div>
                    <p className="mt-1 text-xs text-content-subtle">
                      建立於 {new Date(account.created_at).toLocaleString("zh-TW")}
                      {resourceCount > 0 ? ` · 私有資源 ${resourceCount} 項` : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      className="btn btn-ghost"
                      type="button"
                      disabled={isSelf}
                      onClick={() => void runAction(
                        () => setAccountDisabled(account.id, !account.disabled),
                        account.disabled ? "啟用帳號失敗" : "停用帳號失敗",
                      )}
                    >
                      {account.disabled ? "啟用" : "停用"}
                    </button>
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
                    <button
                      className="btn btn-danger"
                      type="button"
                      disabled={isSelf || !account.disabled || resourceCount > 0}
                      title={resourceCount > 0 ? "請先移除或轉移帳號擁有的私有資源" : undefined}
                      onClick={() => {
                        if (!window.confirm(`確定刪除帳號「${account.username}」？`)) return;
                        void runAction(() => deleteAccount(account.id), "刪除帳號失敗");
                      }}
                    >
                      刪除
                    </button>
                  </div>
                </article>
              );
            })}
            {accounts.length === 0 && (
              <div className="p-8 text-center text-sm text-content-muted">尚無帳號資料</div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

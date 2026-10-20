import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  createAccount,
  deleteAccount,
  listAccounts,
  revokeAccountSessions,
  setAccountDisabled,
  updateAdminScope,
  type Account,
  type AdminScopeResources,
  type AssignableAccountRole,
} from "../api/auth";
import AccountAccessFields, {
  useAccountAccessForm,
} from "../components/accounts/AccountAccessFields";
import AccountPasswordResetDialog from "../components/accounts/AccountPasswordResetDialog";
import AccountRoleDialog from "../components/accounts/AccountRoleDialog";
import AccountRowMenu from "../components/accounts/AccountRowMenu";
import {
  formatFullTime,
  formatRelative,
  sortByLeastRecentActivity,
} from "../components/accounts/accountActivity";
import AdminScopeFields, { EMPTY_SCOPE_RESOURCES } from "../components/accounts/AdminScopeFields";
import AdminScopePanel from "../components/accounts/AdminScopePanel";
import FormalAccountAccessPanel from "../components/accounts/FormalAccountAccessPanel";
import TemporaryBatchPanel from "../components/accounts/TemporaryBatchPanel";
import { useAuth } from "../context/AuthContext";
import { useNavigationGuard } from "../context/NavigationGuardContext";
import { useAdminSubView } from "../hooks/useAdminSubView";

// 「專案與權限 → 帳號」分頁內的第二層：建立（正式／臨時）與編輯／管理。
const ACCOUNT_VIEWS = [
  "accounts",
  "accounts/temporary",
  "accounts/manage",
] as const;

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

function getDeleteDisabledReason(account: Account, resourceCount: number): string | undefined {
  if (resourceCount > 0) {
    return "請先移除或轉移帳號擁有的私有資源";
  }
  if (!account.disabled) {
    return "需先停用帳號才可刪除";
  }
  return undefined;
}

function matchesAccountQuery(account: { username: string; role: string }, query: string): boolean {
  const needle = query.trim().toLowerCase();
  return !needle || account.username.toLowerCase().includes(needle) || account.role.toLowerCase() === needle;
}

export default function Accounts() {
  const { account: currentAccount } = useAuth();
  const isRoot = currentAccount?.role === "root";
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AssignableAccountRole>("user");
  const [view, setView] = useAdminSubView("Access", "accounts", ACCOUNT_VIEWS);
  const mainTab = view === "accounts/manage" ? "manage" : "create";
  const creationMode = view === "accounts/temporary" ? "temporary" : "formal";
  const setMainTab = (next: "create" | "manage") =>
    setView(next === "manage" ? "accounts/manage" : "accounts");
  const setCreationMode = (next: "formal" | "temporary") =>
    setView(next === "temporary" ? "accounts/temporary" : "accounts");
  const [hasOpenedBatches, setHasOpenedBatches] = useState(false);
  const [createdNotice, setCreatedNotice] = useState<string | null>(null);
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null);
  const [accountQuery, setAccountQuery] = useState("");
  const { requestNavigation } = useNavigationGuard();
  // 切換正在編輯的帳號會卸載那個面板；有未儲存的修改先問，不要默默丟掉。
  const switchEditingAccount = (next: string | null) => {
    if (next === editingAccountId) return;
    requestNavigation(() => setEditingAccountId(next));
  };
  const [editingScopeAccountId, setEditingScopeAccountId] = useState<string | null>(null);
  const [roleChangeAccount, setRoleChangeAccount] = useState<Account | null>(
    null,
  );
  const [passwordResetAccount, setPasswordResetAccount] = useState<Account | null>(
    null,
  );
  // 清理帳號時要先看最久沒人用的；預設維持後端的帳號名稱順序。
  const [sortMode, setSortMode] = useState<"name" | "idle">("name");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accessForm = useAccountAccessForm("formal-account-create");
  // 建立管理員時一起設資源上限，不必建完再從更多選單找。
  const [newAdminScoped, setNewAdminScoped] = useState(false);
  const [newAdminScope, setNewAdminScope] = useState<AdminScopeResources>(EMPTY_SCOPE_RESOURCES);
  // 受限 admin 開出來的 admin 不能不設限（後端沒有上限列就是看得到全部）：
  // 切到管理員角色時先勾上並預選建立者自己看得到的全部，再讓他往下縮。
  useEffect(() => {
    if (role !== "admin" || isRoot || !accessForm.options) return;
    const visible = accessForm.options;
    setNewAdminScoped(true);
    setNewAdminScope({
      projects: visible.projects.map((option) => option.id),
      avatar_characters: visible.avatar_characters.map((option) => option.id),
      custom_voices: visible.custom_voices.map((option) => option.id),
      avatar_mascots: (visible.avatar_mascots ?? []).map((option) => option.id),
      avatar_backgrounds: (visible.avatar_backgrounds ?? []).map((option) => option.id),
    });
  }, [role, isRoot, accessForm.options]);

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

  useEffect(() => {
    if (mainTab === "manage" || creationMode === "temporary") {
      setHasOpenedBatches(true);
    }
  }, [mainTab, creationMode]);

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
      const createdUsername = username.trim();
      const created = await createAccount({
        username: createdUsername,
        password,
        role,
        ...(accessForm.complete ? { access: accessForm.access } : {}),
      });
      if (role === "admin" && newAdminScoped) {
        // 帳號已經建好；上限寫失敗要講清楚，不能讓人以為沒建成功。
        try {
          await updateAdminScope(created.id, { scoped: true, resources: newAdminScope });
        } catch (scopeError) {
          setError(`帳號「${createdUsername}」已建立，但資源上限沒有存成功：${errorMessage(scopeError, "")}。請到「編輯／管理」再設一次。`);
        }
      }
      setUsername("");
      setPassword("");
      setRole("user");
      setNewAdminScoped(false);
      setNewAdminScope(EMPTY_SCOPE_RESOURCES);
      setCreatedNotice(`正式帳號「${createdUsername}」建立成功！可切換至「編輯／管理」查看。`);
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
      {/* 第一層分頁在外層頁首；這一層用分段控制，視覺上明顯低一階，不再疊一條底線分頁。 */}
      <div
        className="mb-5 inline-flex rounded-lg border border-border bg-surface-sunken p-1"
        aria-label="帳號功能"
        role="tablist"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const tabs = event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]');
          const next = event.key === "Home" ? 0 : event.key === "End" ? 1 : mainTab === "create" ? 1 : 0;
          tabs[next]?.focus();
          tabs[next]?.click();
        }}
      >
        {([
          ["create", "建立帳號"],
          ["manage", "編輯／管理"],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            className={`whitespace-nowrap rounded-md px-4 py-1.5 text-sm font-semibold transition-colors ${
              mainTab === id
                ? "bg-surface-raised text-content shadow-sm"
                : "text-content-muted hover:text-content"
            }`}
            type="button"
            role="tab"
            id={`accounts-${id}-tab`}
            aria-controls="accounts-main-panel"
            aria-selected={mainTab === id}
            tabIndex={mainTab === id ? 0 : -1}
            onClick={() => {
              setMainTab(id);
              setError(null);
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {createdNotice && (
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary/30 bg-primary/10 px-4 py-3 text-sm text-primary" role="status">
          <span>{createdNotice}</span>
          <button
            className="btn btn-primary text-xs"
            type="button"
            onClick={() => {
              setCreatedNotice(null);
              setMainTab("manage");
            }}
          >
            前往編輯／管理查看
          </button>
        </div>
      )}

      <div
        id="accounts-main-panel"
        role="tabpanel"
        aria-labelledby={`accounts-${mainTab}-tab`}
      >
        {mainTab === "create" && (
          <div>
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
              </button>
            </nav>

            {creationMode === "formal" && (
              <section className="card mb-6 overflow-hidden">
                <header className="border-b border-border px-5 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="card-title">新增正式帳號</h2>
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
                        <option value="admin">管理員</option>
                      </select>
                    </label>
                  </div>

                  {role === "user" ? (
                    <section className="border-t border-border" aria-labelledby="new-account-access-title">
                      <div className="px-5 py-4">
                        <h3 id="new-account-access-title" className="card-title">資源權限</h3>
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
                    <>
                      <section className="border-t border-border" aria-labelledby="new-admin-defaults-title">
                        <div className="px-5 py-4">
                          <h3 id="new-admin-defaults-title" className="card-title">登入預設值</h3>
                          <p className="mt-1 text-xs text-content-muted">
                            管理員看得到全部資源；這裡只決定他登入後預設的專案、人物與聲音。
                          </p>
                        </div>
                        <AccountAccessFields form={accessForm} role="admin" />
                      </section>
                      <section className="border-t border-border px-5 pb-4" aria-labelledby="new-admin-scope-title">
                        <h3 id="new-admin-scope-title" className="card-title pt-4">資源上限</h3>
                        <p className="mt-1 text-xs text-content-muted">
                          要限制這位管理員看得到、分得出去的資源，在這裡勾；不勾就是不設限。
                        </p>
                        <AdminScopeFields
                          options={accessForm.options}
                          loading={accessForm.loading}
                          scoped={newAdminScoped}
                          canUnrestrict={isRoot}
                          selection={newAdminScope}
                          onScopedChange={setNewAdminScoped}
                          onSelectionChange={setNewAdminScope}
                        />
                      </section>
                    </>
                  )}

                  <div className="flex flex-col gap-3 border-t border-border bg-surface-sunken px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                    <p className="text-xs text-content-muted">
                      建立後可切換至「編輯／管理」分頁隨時調整。
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
            )}

          </div>
        )}

        {mainTab === "manage" && (
          // 不加 overflow-hidden：列上的「更多動作」選單要能超出卡片邊界。
          <section className="card mb-6">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
              <div className="flex items-center gap-3">
                <h2 className="card-title">正式帳號列表</h2>
                <span className="chip">{accounts.length} 個帳號</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  className="input w-40 py-1.5 text-xs sm:text-sm"
                  type="search"
                  aria-label="搜尋帳號"
                  placeholder="搜尋帳號"
                  value={accountQuery}
                  onChange={(event) => setAccountQuery(event.target.value)}
                />
                <label className="flex items-center gap-2 text-xs text-content-muted sm:text-sm">
                  排序
                  <select
                    className="input w-auto py-1.5 text-xs sm:text-sm"
                    value={sortMode}
                    onChange={(event) => setSortMode(event.target.value as "name" | "idle")}
                  >
                    <option value="name">帳號名稱</option>
                    <option value="idle">最久未使用優先</option>
                  </select>
                </label>
                <button
                  className="btn btn-ghost text-xs sm:text-sm"
                  type="button"
                  onClick={() => setMainTab("create")}
                >
                  + 建立新帳號
                </button>
                <button
                  className="btn btn-ghost text-xs sm:text-sm"
                  type="button"
                  onClick={() => void reload()}
                  disabled={loading}
                >
                  重新整理
                </button>
              </div>
            </div>
            {/* 只有第一次載入才換成載入中：操作後重新整理若卸載整個列表，焦點會掉回 body。 */}
            {loading && accounts.length === 0 ? (
              <div className="p-8 text-center text-sm text-content-muted" role="status">載入帳號中…</div>
            ) : (
              <div className="divide-y divide-border">
                {(sortMode === "idle" ? sortByLeastRecentActivity(accounts) : accounts)
                  .filter((account) => matchesAccountQuery(account, accountQuery))
                  .map((account) => {
                  const isSelf = account.id === currentAccount?.id;
                  const isFormal = (
                    account.kind ?? account.account_type ?? "formal"
                  ) === "formal";
                  // 與後端 ensure_can_manage_account 對齊：ROOT 管所有人，
                  // admin 管自己直接建立的帳號（含自己開出來的 admin）。
                  // 列表看得到整棵子樹，但只有直屬下一層動得了。
                  const canManage = !isSelf && isFormal && (
                    isRoot
                      ? account.role !== "root"
                      : account.created_by === currentAccount?.id
                  );
                  const resourceCount = ownedResourceCount(account);
                  const grantCount = grantedResourceCount(account);
                  const editingAccess = editingAccountId === account.id;
                  // 資源上限只對管理員有意義。
                  const canEditScope = canManage && account.role === "admin";
                  const editingScope = editingScopeAccountId === account.id;
                  return (
                    <article key={account.id} className="px-5 py-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium">{account.username}</span>
                            <span className="chip">
                              {account.role === "root" ? "ROOT" : account.role}
                            </span>
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
                            {account.kiosk && (
                              <span className="chip border-primary/30 text-primary">
                                展示機台
                              </span>
                            )}
                            {canManage && (
                              <span className="chip" title="已授權的資源項目數">
                                {grantCount > 0 ? `授權 ${grantCount} 項` : "未授權"}
                              </span>
                            )}
                            {/* 管理員本來就能進後台；只有一般使用者被特別開放時才值得標出來。 */}
                            {canManage && account.role === "user" && account.admin_portal_access && (
                              <span className="chip">可進後台</span>
                            )}
                          </div>
                          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-content-subtle">
                            <span>
                              {account.last_login_at ? (
                                <>
                                  最後登入{" "}
                                  <time
                                    dateTime={account.last_login_at}
                                    title={formatFullTime(account.last_login_at)}
                                  >
                                    {formatRelative(account.last_login_at)}
                                  </time>
                                </>
                              ) : (
                                "從未登入"
                              )}
                            </span>
                            {account.api_key_last_used_at && (
                              <span>
                                API 最近使用{" "}
                                <time
                                  dateTime={account.api_key_last_used_at}
                                  title={formatFullTime(account.api_key_last_used_at)}
                                >
                                  {formatRelative(account.api_key_last_used_at)}
                                </time>
                              </span>
                            )}
                            <span>
                              建立於{" "}
                              <time
                                dateTime={account.created_at}
                                title={formatFullTime(account.created_at)}
                              >
                                {new Date(account.created_at).toLocaleDateString("zh-TW")}
                              </time>
                            </span>
                            {resourceCount > 0 && <span>私有資源 {resourceCount} 項</span>}
                          </p>
                        </div>
                        {canManage && (
                          <div className="flex items-center gap-2 self-start sm:self-auto">
                            <button
                              className={editingAccess ? "btn btn-primary" : "btn btn-ghost"}
                              type="button"
                              aria-expanded={editingAccess}
                              onClick={() => switchEditingAccount(
                                editingAccess ? null : account.id,
                              )}
                            >
                              資源權限
                            </button>
                            <AccountRowMenu
                              accountName={account.username}
                              groups={[
                                {
                                  id: "settings",
                                  label: "帳號設定",
                                  items: [
                                    // 資源上限只對管理員有意義。
                                    ...(canEditScope
                                      ? [{
                                        id: "scope",
                                        label: editingScope ? "收起資源上限" : "資源上限",
                                        onSelect: () => setEditingScopeAccountId(
                                          editingScope ? null : account.id,
                                        ),
                                      }]
                                      : []),
                                    ...(isRoot
                                      ? [
                                        {
                                          id: "role",
                                          label: "變更角色",
                                          onSelect: () => setRoleChangeAccount(account),
                                        },
                                        {
                                          id: "password",
                                          label: "重設密碼",
                                          onSelect: () => setPasswordResetAccount(account),
                                        },
                                      ]
                                      : []),
                                  ],
                                },
                                {
                                  id: "danger",
                                  label: "安全與危險",
                                  items: [
                                    {
                                      id: "revoke",
                                      label: "登出所有裝置",
                                      onSelect: () => void runAction(
                                        () => revokeAccountSessions(account.id),
                                        "撤銷登入階段失敗",
                                      ),
                                    },
                                    {
                                      id: "disable",
                                      label: account.disabled ? "啟用" : "停用",
                                      onSelect: () => void runAction(
                                        () => setAccountDisabled(account.id, !account.disabled),
                                        account.disabled ? "啟用帳號失敗" : "停用帳號失敗",
                                      ),
                                    },
                                    {
                                      id: "delete",
                                      label: "刪除",
                                      danger: true,
                                      disabledReason: getDeleteDisabledReason(
                                        account,
                                        resourceCount,
                                      ),
                                      onSelect: () => {
                                        if (!window.confirm(
                                          `確定刪除帳號「${account.username}」？`,
                                        )) return;
                                        void runAction(
                                          () => deleteAccount(account.id),
                                          "刪除帳號失敗",
                                        );
                                      },
                                    },
                                  ],
                                },
                              ]}
                            />
                          </div>
                        )}
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
        )}

        {hasOpenedBatches && (
          <div hidden={mainTab === "create" && creationMode === "formal"}>
            <TemporaryBatchPanel view={mainTab} />
          </div>
        )}
      </div>

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

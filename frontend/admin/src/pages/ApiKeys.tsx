import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import {
  createAccountApiKey,
  listAccountApiKeys,
  revokeAccountApiKey,
  type AccountApiKey,
} from "../api/apiKeys";
import { listAccounts, type Account } from "../api/auth";
import ConfirmModal from "../components/ConfirmModal";
import StatusAlert from "../components/StatusAlert";
import { useAuth } from "../context/AuthContext";
import { useNavigation } from "../context/NavigationContext";

const inputClass = "w-full rounded-lg border border-border bg-surface-raised px-3 py-2 text-sm text-content focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:opacity-50";

function defaultExpiry(): string {
  const date = new Date(Date.now() + 90 * 24 * 60 * 60 * 1000);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "操作失敗，請稍後再試。";
}

function dateLabel(value: string | null): string {
  return value ? new Date(value).toLocaleString("zh-TW") : "—";
}

export default function ApiKeys() {
  const { account } = useAuth();
  const { navigateTo } = useNavigation();
  const [owners, setOwners] = useState<Account[]>([]);
  const [ownerId, setOwnerId] = useState(account?.id ?? "");
  const [keys, setKeys] = useState<AccountApiKey[]>([]);
  const [label, setLabel] = useState("");
  const [expiry, setExpiry] = useState(defaultExpiry);
  const [noExpiry, setNoExpiry] = useState(false);
  const [secret, setSecret] = useState<{ value: string; owner: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<AccountApiKey | null>(null);
  const busyRef = useRef(false);
  const requestRef = useRef(0);
  const isFormal = account && (account.kind ?? account.account_type ?? "formal") === "formal";
  const isAdmin = account?.role === "root" || account?.role === "admin";
  const owner = owners.find((item) => item.id === ownerId) ?? account;

  const reload = useCallback(async () => {
    const request = ++requestRef.current;
    setLoading(true);
    try {
      const next = await listAccountApiKeys(ownerId);
      if (request === requestRef.current) setKeys(next);
    } catch (reason) {
      if (request === requestRef.current) setError(message(reason));
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  }, [ownerId]);

  useEffect(() => {
    if (!isFormal) { setLoading(false); return; }
    setKeys([]);
    setError(null);
    void reload();
    return () => { requestRef.current += 1; };
  }, [isFormal, reload]);

  useEffect(() => {
    if (!isFormal || !isAdmin || !account) return;
    let active = true;
    void listAccounts().then((items) => {
      if (!active) return;
      setOwners(items.filter((item) => (
        (item.kind ?? item.account_type ?? "formal") === "formal"
        && (item.id === account.id || (
          account.role === "root" ? item.role !== "root" : item.created_by === account.id
        ))
      )));
    }).catch(() => {
      if (active) setError("無法取得其他帳號；仍可管理自己的 API 金鑰。");
    });
    return () => { active = false; };
  }, [account, isAdmin, isFormal]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busyRef.current || secret) return;
    const date = new Date(expiry);
    if (!label.trim()) { setError("請輸入金鑰名稱。"); return; }
    if (!noExpiry && (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now())) {
      setError("到期時間必須是有效的未來時間。"); return;
    }
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await createAccountApiKey({
        label: label.trim(),
        user_id: ownerId,
        expires_at: noExpiry ? null : date.toISOString(),
      });
      // Keep the one-time value even when refreshing metadata fails.
      setSecret({ value: result.key, owner: owner?.username ?? ownerId });
      setCopied(false);
      setLabel("");
      await reload();
    } catch (reason) {
      setError(message(reason));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function revoke() {
    if (!revokeTarget || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await revokeAccountApiKey(revokeTarget.key_id);
      setRevokeTarget(null);
      setNotice("已撤銷金鑰。既有紀錄保留供查核。");
      await reload();
    } catch (reason) { setError(message(reason)); }
    finally { busyRef.current = false; setBusy(false); }
  }

  async function copySecret() {
    if (!secret) return;
    try {
      if (!navigator.clipboard) throw new Error("請手動選取並複製金鑰。");
      await navigator.clipboard.writeText(secret.value);
      setCopied(true);
    } catch (reason) { setError(message(reason)); }
  }

  if (!isFormal) {
    return <p className="p-6 text-content-muted">臨時帳號不能建立 API 金鑰。</p>;
  }

  return (
    <div className="page-scroll p-6 lg:p-8">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="page-title">帳號 API 金鑰</h1>
          <p className="page-subtitle">供服務串接使用，權限隨所屬帳號的角色與資源授權變動。</p>
        </div>
        {isAdmin && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => navigateTo("Accounts", "manage")}
          >
            返回帳號管理
          </button>
        )}
      </header>
      <div className="space-y-6">
        {error && <StatusAlert type="error" message={error} onDismiss={() => setError(null)} />}
        {notice && <StatusAlert type="success" message={notice} onDismiss={() => setNotice(null)} />}
        <section className="space-y-3" aria-label="金鑰所屬帳號">
          <label htmlFor="api-key-owner" className="block text-sm font-medium">所屬帳號</label>
          <select
            id="api-key-owner"
            value={ownerId}
            disabled={busy || Boolean(secret)}
            className={inputClass}
            onChange={(event) => {
              setOwnerId(event.target.value);
              setNotice(null);
            }}
          >
            <option value={account!.id}>
              {account!.username}（自己 · {account!.role}）
            </option>
            {owners.filter((item) => item.id !== account!.id).map((item) => (
              <option key={item.id} value={item.id}>
                {item.username}（{item.role}{item.disabled ? " · 已停用" : ""}）
              </option>
            ))}
          </select>
          <p className="text-sm text-content-muted">目前管理：{owner?.username}（{owner?.role}）。帳號停用、刪除或收回資源授權後，金鑰也會受限制。</p>
        </section>
        {secret ? (
          <section aria-label="新金鑰只顯示一次" className="space-y-3 rounded-xl border border-primary/40 bg-surface-raised p-5">
            <h2 className="card-title">請保存金鑰：只顯示這一次</h2>
            <p className="text-sm text-content-muted">所屬帳號：{secret.owner}。關閉或離開本頁後無法再次取得完整金鑰。</p>
            <code className="block break-all rounded-lg bg-surface-sunken p-3 text-sm select-all">{secret.value}</code>
            <div className="flex flex-wrap gap-3">
              <button type="button" className="btn btn-primary" onClick={() => void copySecret()}>{copied ? "已複製" : "複製完整金鑰"}</button>
              <button type="button" className="btn btn-ghost" onClick={() => { setSecret(null); setCopied(false); }}>我已保存，關閉</button>
            </div>
          </section>
        ) : (
          <form aria-label="建立帳號 API 金鑰" onSubmit={(event) => void create(event)} className="space-y-4 rounded-xl border border-border bg-surface p-5">
            <h2 className="card-title">建立金鑰</h2>
            <div>
              <label className="mb-1 block text-sm" htmlFor="api-key-label">名稱</label>
              <input
                id="api-key-label"
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                required
                maxLength={120}
                disabled={busy}
                placeholder="例：合作夥伴 ASR"
                className={inputClass}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm" htmlFor="api-key-expiry">
                到期時間（本地時間，預設 90 天）
              </label>
              <input
                id="api-key-expiry"
                type="datetime-local"
                value={expiry}
                onChange={(event) => setExpiry(event.target.value)}
                disabled={noExpiry || busy}
                className={inputClass}
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={noExpiry}
                disabled={busy}
                onChange={(event) => setNoExpiry(event.target.checked)}
              />
              不設到期時間
            </label>
            <button type="submit" className="btn btn-primary" disabled={busy || !label.trim()}>
              {busy ? "建立中…" : "建立 API 金鑰"}
            </button>
          </form>
        )}
        <section aria-label="API 金鑰列表">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="card-title">金鑰紀錄</h2>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={loading || busy}
              onClick={() => { setError(null); void reload(); }}
            >
              重新整理金鑰
            </button>
          </div>
          {loading ? (
            <p role="status" className="text-sm text-content-muted">載入金鑰中…</p>
          ) : keys.length === 0 ? (
            <p className="text-sm text-content-muted">此帳號尚未建立 API 金鑰。</p>
          ) : (
            <div className="divide-y divide-border rounded-xl border border-border bg-surface">
              {keys.map((key) => {
                const expired = key.expires_at
                  && new Date(key.expires_at).getTime() <= Date.now();
                const state = key.revoked_at ? "已撤銷" : expired ? "已到期" : "有效";
                return (
                  <article key={key.key_id} className="flex flex-col gap-3 p-5 sm:flex-row sm:items-start">
                    <div className="min-w-0 flex-1 space-y-1">
                      <h3 className="break-words font-medium">
                        {key.label} <span className="chip">{state}</span>
                      </h3>
                      <p className="break-all font-mono text-xs text-content-muted">
                        {key.token_prefix}… · ID：{key.key_id}
                      </p>
                      <p className="text-xs text-content-muted">
                        建立：{dateLabel(key.created_at)} · 到期：{key.expires_at ? dateLabel(key.expires_at) : "無期限"}
                      </p>
                      <p className="text-xs text-content-muted">
                        最後使用：{dateLabel(key.last_used_at)} · 請求次數：{key.request_count}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn btn-danger"
                      disabled={busy || Boolean(key.revoked_at)}
                      aria-label={`撤銷 ${key.label}`}
                      onClick={() => setRevokeTarget(key)}
                    >
                      撤銷
                    </button>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
      <ConfirmModal
        open={Boolean(revokeTarget)}
        title="撤銷 API 金鑰"
        message={`確定撤銷「${revokeTarget?.label ?? ""}」？使用它的服務將無法繼續存取。`}
        confirmLabel={busy ? "撤銷中…" : "確認撤銷"}
        danger
        onConfirm={() => void revoke()}
        onCancel={() => { if (!busy) setRevokeTarget(null); }}
      />
    </div>
  );
}

import {
  useCallback,
  useEffect,
  useState,
} from "react";

import {
  createTemporaryBatch,
  listTemporaryBatches,
  revokeTemporaryBatch,
  setTemporaryBatchAdminPortalAccess,
  type TemporaryBatchAudit,
  type TemporaryBatchResult,
} from "../../api/auth";
import AccountAccessFields, {
  useAccountAccessForm,
} from "./AccountAccessFields";

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function stateLabel(state?: string | null): string {
  switch (state) {
    case "active":
      return "使用中";
    case "expired":
      return "已到期";
    case "revoked":
      return "已撤銷";
    default:
      return "尚未啟用";
  }
}

function batchStateLabel(batch: TemporaryBatchAudit): string {
  if (batch.revoked_at) return "已撤銷";
  if (batch.state) return stateLabel(batch.state);
  return batch.first_used_at ? "使用中" : "尚未啟用";
}

function dateLabel(value?: string | null): string {
  return value ? new Date(value).toLocaleString("zh-TW") : "—";
}

function remainingLabel(seconds: number | null): string {
  if (seconds === null) return "尚未計時";
  const minutes = Math.max(0, Math.ceil(seconds / 60));
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `剩餘 ${hours} 小時 ${minutes % 60} 分` : `剩餘 ${minutes} 分`;
}

function revokeButtonLabel(isRevoking: boolean, isRevoked: boolean): string {
  if (isRevoking) return "撤銷中…";
  if (isRevoked) return "已撤銷";
  return "撤銷整批";
}

function portalAccessButtonLabel(isUpdating: boolean, hasAccess: boolean): string {
  if (isUpdating) return "更新中…";
  return hasAccess ? "關閉後台權限" : "開啟後台權限";
}

export default function TemporaryBatchPanel() {
  const accessForm = useAccountAccessForm("temporary-account-batch");
  const [batches, setBatches] = useState<TemporaryBatchAudit[]>([]);
  const [result, setResult] = useState<TemporaryBatchResult | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [updatingPortal, setUpdatingPortal] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const loadBatches = useCallback(async () => {
    setHistoryLoading(true);
    setError(null);
    try {
      setBatches(await listTemporaryBatches());
    } catch (reason) {
      setError(messageFrom(reason, "無法載入臨時帳號批次紀錄"));
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBatches();
  }, [loadBatches]);

  async function generateBatch() {
    if (!accessForm.complete) {
      setError("每一類至少選擇一項授權資源，並指定登入後預設值。");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const created = await createTemporaryBatch(accessForm.access);
      setResult(created);
      try {
        setBatches(await listTemporaryBatches());
      } catch {
        setError("帳號已成功產生，但批次紀錄暫時無法更新。請先保存下方密碼。");
      }
    } catch (reason) {
      setError(messageFrom(reason, "無法產生臨時帳號"));
    } finally {
      setSubmitting(false);
    }
  }

  function reload() {
    accessForm.reload();
    void loadBatches();
  }

  const displayedError = error ?? accessForm.error;

  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      window.setTimeout(() => setCopied((current) => current === key ? null : current), 2500);
    } catch {
      setError("無法寫入剪貼簿，請手動複製密碼。");
    }
  }

  async function revoke(batchId: string) {
    setRevoking(batchId);
    setError(null);
    try {
      const updated = await revokeTemporaryBatch(batchId);
      setBatches((current) => current.map(
        (batch) => batch.batch_id === batchId ? updated : batch,
      ));
    } catch (reason) {
      setError(messageFrom(reason, "撤銷批次失敗"));
    } finally {
      setRevoking(null);
    }
  }

  async function updatePortalAccess(batch: TemporaryBatchAudit) {
    setUpdatingPortal(batch.batch_id);
    setError(null);
    try {
      const updated = await setTemporaryBatchAdminPortalAccess(
        batch.batch_id,
        !(batch.admin_portal_access ?? false),
      );
      setBatches((current) => current.map(
        (item) => item.batch_id === batch.batch_id ? updated : item,
      ));
    } catch (reason) {
      setError(messageFrom(reason, "更新管理後台權限失敗"));
    } finally {
      setUpdatingPortal(null);
    }
  }

  return (
    <section className="card mb-6 overflow-hidden">
      <header className="flex flex-col gap-3 border-b border-border px-5 py-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="card-title">臨時帳號批次</h2>
            <span className="chip">每批固定 5 組</span>
          </div>
          <p className="mt-1 text-sm text-content-muted">
            密碼在首次登入後啟動 72 小時效期；請先選擇這批帳號可使用的資源。
          </p>
        </div>
        <button className="btn btn-ghost self-start" type="button" onClick={reload} disabled={accessForm.loading || historyLoading}>
          重新整理資源
        </button>
      </header>

      {displayedError && (
        <div className="mx-5 mt-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger" role="alert">
          {displayedError}
        </div>
      )}

      <AccountAccessFields form={accessForm} />

      <div className="flex flex-col gap-3 border-t border-border bg-surface-sunken px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-content-muted">偏好值不可用時，已自動改用目前授權清單的第一項。</p>
        <button className="btn btn-primary" type="button" onClick={() => void generateBatch()} disabled={accessForm.loading || submitting || !accessForm.complete}>
          {submitting ? "產生中…" : "產生 5 組帳號"}
        </button>
      </div>

      {result && (
        <section className="border-t border-border px-5 py-5" aria-labelledby="temporary-result-title">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <h3 id="temporary-result-title" className="card-title">本次臨時密碼</h3>
            </div>
            <button
              className="btn btn-ghost self-start"
              type="button"
              onClick={() => void copy(
                result.credentials.map((item) => item.password).join("\n"),
                "all",
              )}
            >
              {copied === "all" ? "已複製全部" : "複製全部"}
            </button>
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {result.credentials.map((credential, index) => (
              <div key={credential.user_id} className="grid gap-2 py-3 sm:grid-cols-[auto_1fr_auto] sm:items-center">
                <span className="text-xs text-content-subtle">{String(index + 1).padStart(2, "0")}</span>
                <code className="break-all font-mono text-sm">{credential.password}</code>
                <button
                  className="btn btn-ghost justify-self-start sm:justify-self-end"
                  type="button"
                  onClick={() => void copy(credential.password, credential.user_id)}
                >
                  {copied === credential.user_id ? "已複製" : "複製密碼"}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="border-t border-border" aria-labelledby="temporary-history-title">
        <div className="px-5 py-4">
          <h3 id="temporary-history-title" className="card-title">批次紀錄</h3>
        </div>
        <div className="divide-y divide-border border-t border-border">
          {batches.map((batch) => {
            const revoked = Boolean(batch.revoked_at || batch.state === "revoked");
            return (
              <article key={batch.batch_id} className="px-5 py-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-sm">建立於 {dateLabel(batch.created_at)}</span>
                      <span className="chip">{batchStateLabel(batch)}</span>
                      <span className="chip">
                        {batch.admin_portal_access ? "可進管理後台" : "不可進管理後台"}
                      </span>
                      <span className="text-xs text-content-subtle">{batch.account_count ?? 5} 組</span>
                    </div>
                    {batch.expires_at && (
                      <p className="mt-1 text-xs text-content-muted">
                        到期 {dateLabel(batch.expires_at)}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2 self-start md:self-auto">
                    <button
                      className="btn btn-ghost"
                      type="button"
                      disabled={revoked || updatingPortal === batch.batch_id}
                      onClick={() => void updatePortalAccess(batch)}
                    >
                      {portalAccessButtonLabel(
                        updatingPortal === batch.batch_id,
                        batch.admin_portal_access ?? false,
                      )}
                    </button>
                    <button
                      className="btn btn-danger"
                      type="button"
                      disabled={revoked || revoking === batch.batch_id}
                      onClick={() => {
                        if (!window.confirm("確定撤銷這一批臨時帳號的剩餘存取權？")) return;
                        void revoke(batch.batch_id);
                      }}
                    >
                      {revokeButtonLabel(revoking === batch.batch_id, revoked)}
                    </button>
                  </div>
                </div>
                {batch.accounts && batch.accounts.length > 0 && (
                  <div className="mt-3 grid gap-x-5 gap-y-2 border-t border-border pt-3 sm:grid-cols-2 xl:grid-cols-3">
                    {batch.accounts.map((account) => (
                      <div key={account.user_id} className="flex min-w-0 items-center justify-between gap-3 text-xs">
                        <span className="min-w-0">
                          <code className="block truncate font-mono text-content-muted">{account.username}</code>
                          <span className="block text-content-subtle">{remainingLabel(account.remaining_seconds)}</span>
                        </span>
                        <span className="chip shrink-0">{stateLabel(account.state)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </article>
            );
          })}
          {!historyLoading && batches.length === 0 && (
            <p className="px-5 py-6 text-center text-sm text-content-muted">尚無臨時帳號批次</p>
          )}
        </div>
      </section>
    </section>
  );
}

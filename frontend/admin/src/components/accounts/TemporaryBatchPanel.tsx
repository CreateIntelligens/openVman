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

type BatchState = NonNullable<TemporaryBatchAudit["state"]>;

function batchState(batch: TemporaryBatchAudit): BatchState {
  if (batch.revoked_at) return "revoked";
  return batch.state ?? (batch.first_used_at ? "active" : "unused");
}

function dateLabel(value?: string | null): string {
  return value ? new Date(value).toLocaleString("zh-TW") : "—";
}

/** 列表上掃讀用：「2026/10/30 15:12」，完整時間放在 title。 */
function shortDateLabel(value: string): string {
  return new Date(value).toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
}

/** 效期從首次登入才開始算，尚未啟用的批次沒有到期日可顯示。 */
function lifetimeLabel(batch: TemporaryBatchAudit, state: BatchState): string {
  if (state === "revoked") {
    return batch.revoked_at ? `撤銷於 ${shortDateLabel(batch.revoked_at)}` : "已撤銷";
  }
  if (batch.expires_at) {
    const at = shortDateLabel(batch.expires_at);
    return state === "expired" ? `已於 ${at} 到期` : `到期 ${at}`;
  }
  return state === "expired" ? "已到期" : "首次登入後開始計時";
}

const STATUS_FILTERS: ReadonlyArray<{ id: "all" | BatchState; label: string }> = [
  { id: "all", label: "全部" },
  { id: "unused", label: stateLabel("unused") },
  { id: "active", label: stateLabel("active") },
  { id: "expired", label: stateLabel("expired") },
  { id: "revoked", label: stateLabel("revoked") },
];

const STATE_TONE: Record<BatchState, string> = {
  unused: "",
  active: "border-success/30 text-success",
  expired: "border-warn/30 text-warn",
  revoked: "border-danger/30 text-danger",
};

const FOCUS_RING = "focus-visible:outline focus-visible:outline-[0.125rem] focus-visible:outline-offset-[0.125rem] focus-visible:outline-primary";

function StateBadge({ state }: { state: BatchState }) {
  return (
    <span className={`chip ${STATE_TONE[state]}`}>
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
      {stateLabel(state)}
    </span>
  );
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

export default function TemporaryBatchPanel({
  view = "create",
}: {
  view?: "create" | "manage";
}) {
  const accessForm = useAccountAccessForm("temporary-account-batch");
  const [batches, setBatches] = useState<TemporaryBatchAudit[]>([]);
  const [result, setResult] = useState<TemporaryBatchResult | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [updatingPortal, setUpdatingPortal] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | BatchState>("all");
  const [expandedBatches, setExpandedBatches] = useState<ReadonlySet<string>>(() => new Set());

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
      // 剛產生的那批預設展開，切到管理頁就看得到這次的密碼。
      setExpandedBatches((current) => new Set(current).add(created.batch_id));
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

  const activeError = view === "create" ? (error ?? accessForm.error) : error;
  const filteredBatches = batches.filter(
    (batch) => statusFilter === "all" || batchState(batch) === statusFilter,
  );
  const stateCounts = batches.reduce<Record<BatchState, number>>(
    (counts, batch) => ({ ...counts, [batchState(batch)]: counts[batchState(batch)] + 1 }),
    { unused: 0, active: 0, expired: 0, revoked: 0 },
  );

  function toggleBatch(batchId: string) {
    setExpandedBatches((current) => {
      const next = new Set(current);
      if (next.has(batchId)) next.delete(batchId);
      else next.add(batchId);
      return next;
    });
  }

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
      {view === "create" && (
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
      )}

      {activeError && (
        <div className="mx-5 mt-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger" role="alert">
          {activeError}
        </div>
      )}

      {view === "create" && (
        <>
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
                  <div key={credential.user_id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2">
                    <span className="text-xs text-content-subtle">{String(index + 1).padStart(2, "0")}</span>
                    <code className="min-w-0 break-all font-mono text-sm">{credential.password}</code>
                    <button
                      className="btn btn-ghost justify-self-end"
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
        </>
      )}

      {view === "manage" && (
        <section aria-labelledby="temporary-history-title">
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4">
            <div className="flex items-center gap-3">
              <h2 id="temporary-history-title" className="card-title">批次紀錄</h2>
              <span className="chip tabular-nums" aria-live="polite">
                {statusFilter === "all"
                  ? `${batches.length} 批`
                  : `${filteredBatches.length} / ${batches.length} 批`}
              </span>
            </div>
            <button
              className={`btn btn-ghost px-3 py-1.5 text-xs sm:text-sm ${FOCUS_RING}`}
              type="button"
              onClick={() => void loadBatches()}
              disabled={historyLoading}
            >
              <span
                aria-hidden="true"
                className={`material-symbols-outlined text-[1.125rem] ${historyLoading ? "animate-spin" : ""}`}
              >
                refresh
              </span>
              重新整理
            </button>
          </div>

          <div
            className="flex flex-wrap gap-2 border-b border-border px-5 pb-4 pt-3"
            role="group"
            aria-label="批次狀態"
          >
            {STATUS_FILTERS.map((option) => {
              const selected = statusFilter === option.id;
              return (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setStatusFilter(option.id)}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${FOCUS_RING} ${
                    selected
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-border text-content-muted hover:border-border-strong hover:text-content"
                  }`}
                >
                  {option.label}
                  <span className={`tabular-nums ${selected ? "opacity-70" : "text-content-subtle"}`}>
                    {option.id === "all" ? batches.length : stateCounts[option.id]}
                  </span>
                </button>
              );
            })}
          </div>

          {/* 只有第一次載入才換成骨架：重新整理時若卸載列表，焦點會掉回 body。 */}
          {historyLoading && batches.length === 0 ? (
            <div className="divide-y divide-border" role="status">
              <span className="sr-only">載入批次紀錄中…</span>
              {[0, 1, 2].map((row) => (
                <div key={row} aria-hidden="true" className="flex items-center gap-3 px-5 py-4">
                  <span className="h-4 w-4 shrink-0 animate-pulse rounded bg-surface-sunken" />
                  <span className="flex flex-1 flex-col gap-2">
                    <span className="h-3.5 w-1/3 animate-pulse rounded bg-surface-sunken" />
                    <span className="h-3 w-1/2 animate-pulse rounded bg-surface-sunken" />
                  </span>
                </div>
              ))}
            </div>
          ) : batches.length === 0 ? (
            <div className="flex flex-col items-center gap-1 px-5 py-10 text-center">
              <span aria-hidden="true" className="material-symbols-outlined text-[2rem] text-content-subtle">
                inventory_2
              </span>
              <p className="text-sm font-medium text-content">尚無臨時帳號批次</p>
              <p className="text-xs text-content-subtle">在「建立帳號」產生的批次會列在這裡。</p>
            </div>
          ) : filteredBatches.length === 0 ? (
            <div className="flex flex-col items-center gap-3 px-5 py-10 text-center">
              <p className="text-sm text-content-muted">沒有符合此狀態的批次紀錄</p>
              <button
                className={`btn btn-ghost px-3 py-1.5 text-xs ${FOCUS_RING}`}
                type="button"
                onClick={() => setStatusFilter("all")}
              >
                顯示全部批次
              </button>
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {filteredBatches.map((batch) => {
                const state = batchState(batch);
                const revoked = state === "revoked";
                const expanded = expandedBatches.has(batch.batch_id);
                const detailsId = `temporary-batch-${batch.batch_id}-accounts`;
                const accounts = batch.accounts ?? [];
                const summary = (
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <time
                        className="text-sm font-semibold text-content"
                        dateTime={batch.created_at}
                        title={`建立於 ${dateLabel(batch.created_at)}`}
                      >
                        {shortDateLabel(batch.created_at)}
                      </time>
                      <StateBadge state={state} />
                      {batch.kiosk && (
                        <span className="chip border-primary/30 text-primary">展示機台</span>
                      )}
                      {batch.admin_portal_access && (
                        <span className="chip">可進管理後台</span>
                      )}
                    </span>
                    <span className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-content-subtle">
                      <span>{batch.account_count ?? (accounts.length || 5)} 組帳號</span>
                      <span>{lifetimeLabel(batch, state)}</span>
                    </span>
                  </span>
                );
                return (
                  <li key={batch.batch_id}>
                    <article>
                      <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:gap-4">
                        {accounts.length > 0 ? (
                          <button
                            type="button"
                            className={`-m-1 flex min-w-0 flex-1 items-start gap-3 rounded-md p-1 text-left ${FOCUS_RING}`}
                            aria-expanded={expanded}
                            aria-controls={detailsId}
                            onClick={() => toggleBatch(batch.batch_id)}
                          >
                            <span
                              aria-hidden="true"
                              className={`material-symbols-outlined text-[1.25rem] text-content-subtle transition-transform ${
                                expanded ? "rotate-90" : ""
                              }`}
                            >
                              chevron_right
                            </span>
                            {summary}
                          </button>
                        ) : (
                          // 沒有帳號明細可展開時不放停用按鈕，摘要文字才讀得到。
                          <div className="flex min-w-0 flex-1 items-start gap-3 pl-8">{summary}</div>
                        )}
                        {!revoked && (
                          <div className="flex flex-wrap gap-2 pl-8 sm:pl-0">
                            <button
                              className={`btn btn-ghost px-3 py-1.5 text-xs sm:text-sm ${FOCUS_RING}`}
                              type="button"
                              disabled={updatingPortal === batch.batch_id}
                              onClick={() => void updatePortalAccess(batch)}
                            >
                              {portalAccessButtonLabel(
                                updatingPortal === batch.batch_id,
                                batch.admin_portal_access ?? false,
                              )}
                            </button>
                            <button
                              className={`btn btn-danger px-3 py-1.5 text-xs sm:text-sm ${FOCUS_RING}`}
                              type="button"
                              disabled={revoking === batch.batch_id}
                              onClick={() => {
                                if (!window.confirm("確定撤銷這一批臨時帳號的剩餘存取權？")) return;
                                void revoke(batch.batch_id);
                              }}
                            >
                              {revokeButtonLabel(revoking === batch.batch_id, revoked)}
                            </button>
                          </div>
                        )}
                      </div>
                      {accounts.length > 0 && (
                        <ol
                          id={detailsId}
                          hidden={!expanded}
                          aria-label="批次內的帳號"
                          className="divide-y divide-border border-t border-border bg-surface-sunken/60 px-5"
                        >
                          {accounts.map((account, index) => {
                            const password = account.password ?? result?.credentials.find(
                              (credential) => credential.user_id === account.user_id,
                            )?.password;
                            return (
                              <li
                                key={account.user_id}
                                className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 py-2.5 sm:pl-8"
                              >
                                <span className="text-xs tabular-nums text-content-subtle">
                                  {String(index + 1).padStart(2, "0")}
                                </span>
                                <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                                  {password ? (
                                    <code className="min-w-0 break-all font-mono text-sm text-content">{password}</code>
                                  ) : (
                                    <span className="text-xs text-content-muted">密碼未保存</span>
                                  )}
                                  <span className="flex flex-wrap items-center gap-2 text-xs">
                                    <StateBadge state={account.state} />
                                    <span className="text-content-subtle">{remainingLabel(account.remaining_seconds)}</span>
                                  </span>
                                </span>
                                <button
                                  className={`btn btn-ghost px-2.5 py-1 text-xs ${FOCUS_RING}`}
                                  type="button"
                                  disabled={!password}
                                  onClick={() => {
                                    if (password) void copy(password, account.user_id);
                                  }}
                                >
                                  <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">
                                    {copied === account.user_id ? "check" : "content_copy"}
                                  </span>
                                  {copied === account.user_id ? "已複製" : "複製密碼"}
                                </button>
                              </li>
                            );
                          })}
                        </ol>
                      )}
                    </article>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}
    </section>
  );
}

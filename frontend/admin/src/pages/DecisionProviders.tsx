import { useCallback, useEffect, useMemo, useState } from "react";

import StatusAlert from "../components/StatusAlert";
import {
  fetchDecisionProviderSettings,
  saveDecisionProviderSettings,
  type DecisionCredentialId,
  type DecisionProviderHop,
  type DecisionProviderSettings,
} from "../api/decisionProviders";

const CREDENTIALS: Array<{
  id: DecisionCredentialId;
  title: string;
  description: string;
}> = [
  {
    id: "clef",
    title: "Clef API key",
    description: "主端點與備援端點共用；Clef 目前可不填 key。",
  },
  {
    id: "jev",
    title: "Jev API key",
    description: "未填時沿用部署環境的 TYPESAFE_API_KEY。",
  },
  {
    id: "openai",
    title: "OpenAI API key",
    description: "用於 OpenAI Decisions 專用 API。",
  },
];

type PageNotice = { type: "success" | "error"; message: string } | null;

export default function DecisionProviders() {
  const [settings, setSettings] = useState<DecisionProviderSettings | null>(null);
  const [order, setOrder] = useState<string[]>([]);
  const [enabled, setEnabled] = useState<Set<string>>(new Set());
  const [keys, setKeys] = useState<Partial<Record<DecisionCredentialId, string>>>({});
  const [clearKeys, setClearKeys] = useState<Set<DecisionCredentialId>>(new Set());
  const [useEnvironmentKeys, setUseEnvironmentKeys] = useState<Set<DecisionCredentialId>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<PageNotice>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setNotice(null);
    try {
      const result = await fetchDecisionProviderSettings();
      setSettings(result);
      setOrder(result.order);
      setEnabled(new Set(result.enabled));
      setKeys({});
      setClearKeys(new Set());
      setUseEnvironmentKeys(new Set());
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "無法載入決策供應商設定。",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const hopsById = useMemo(
    () => new Map((settings?.providers ?? []).map((provider) => [provider.id, provider])),
    [settings],
  );

  function moveHop(id: string, offset: -1 | 1) {
    setOrder((current) => {
      const index = current.indexOf(id);
      const destination = index + offset;
      if (index < 0 || destination < 0 || destination >= current.length) return current;
      const next = [...current];
      [next[index], next[destination]] = [next[destination], next[index]];
      return next;
    });
  }

  function toggleHop(id: string) {
    setEnabled((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setNotice(null);
    try {
      const credentials = Object.fromEntries(
        Object.entries(keys)
          .filter(([, value]) => Boolean(value?.trim()))
          .map(([id, value]) => [id, value!.trim()]),
      ) as Partial<Record<DecisionCredentialId, string>>;
      const result = await saveDecisionProviderSettings({
        order,
        enabled: order.filter((id) => enabled.has(id)),
        credentials,
        clear_credentials: [...clearKeys],
        use_environment_credentials: [...useEnvironmentKeys],
      });
      setSettings(result);
      setOrder(result.order);
      setEnabled(new Set(result.enabled));
      setKeys({});
      setClearKeys(new Set());
      setUseEnvironmentKeys(new Set());
      setNotice({ type: "success", message: "決策供應鏈設定已儲存。" });
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "儲存決策供應鏈設定失敗。",
      });
    } finally {
      setSaving(false);
    }
  }

  function providerStatus(credentialId: DecisionCredentialId): DecisionProviderHop | undefined {
    return settings?.providers.find((provider) => provider.provider === credentialId);
  }

  function setCredentialAction(
    credentialId: DecisionCredentialId,
    action: "clear" | "environment",
  ) {
    setKeys((current) => ({ ...current, [credentialId]: "" }));
    setClearKeys((current) => {
      const next = new Set(current);
      if (action === "clear") next.add(credentialId);
      else next.delete(credentialId);
      return next;
    });
    setUseEnvironmentKeys((current) => {
      const next = new Set(current);
      if (action === "environment") next.add(credentialId);
      else next.delete(credentialId);
      return next;
    });
  }

  return (
    <div className="page-scroll">
      <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-border bg-surface-raised/90 px-8 py-4 backdrop-blur-md">
        <div>
          <h1 className="page-title">決策模型</h1>
          <p className="page-subtitle">設定本地規則無法判斷時使用的決策供應鏈。</p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading || saving}
          className="rounded-lg border border-border px-4 py-2 text-sm text-content-muted transition-colors hover:border-border-strong hover:bg-surface hover:text-content disabled:opacity-50"
        >
          {loading ? "載入中…" : "重新載入"}
        </button>
      </header>

      <div className="mx-auto max-w-5xl space-y-6 p-6 md:p-8">
        {notice && <StatusAlert type={notice.type} message={notice.message} />}

        <section className="rounded-xl border border-border bg-surface-raised p-5 md:p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-base font-semibold text-content">供應商順序</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-content-muted">
                Brain 依序嘗試啟用的供應商。每個有效答案會立即返回；連線、逾時、驗證或回應錯誤時才會進入下一個。
              </p>
            </div>
            <span className="shrink-0 text-xs text-content-subtle">使用 ↑ ↓ 調整優先順序</span>
          </div>

          {loading && !settings ? (
            <div className="mt-5 space-y-3" aria-label="正在載入供應商設定">
              {[0, 1, 2, 3].map((row) => (
                <div key={row} className="h-20 animate-pulse rounded-lg bg-surface-sunken" />
              ))}
            </div>
          ) : settings ? (
            <ol className="mt-5 divide-y divide-border border-y border-border">
              {order.map((id, index) => {
                const hop = hopsById.get(id);
                if (!hop) return null;
                const active = enabled.has(id);
                return (
                  <li
                    key={id}
                    data-testid={`provider-${id}`}
                    className={`flex flex-col gap-4 py-4 sm:flex-row sm:items-center sm:gap-5 ${active ? "" : "opacity-65"}`}
                  >
                    <span className="w-7 shrink-0 text-center font-mono text-sm tabular-nums text-content-subtle" aria-label={`優先順序 ${index + 1}`}>
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-medium text-content">{hop.label}</h3>
                        {!active && <span className="rounded bg-surface-sunken px-2 py-0.5 text-xs text-content-subtle">已停用</span>}
                      </div>
                      <p className="mt-1 break-all font-mono text-xs text-content-muted">{hop.endpoint}</p>
                      <p className="mt-1 text-xs text-content-subtle">模型：{hop.model}</p>
                    </div>
                    <label className="flex min-h-10 shrink-0 items-center gap-2 text-sm text-content-muted">
                      <input
                        type="checkbox"
                        checked={active}
                        onChange={() => toggleHop(id)}
                        aria-label={`啟用 ${hop.label}`}
                        className="size-4 accent-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                      />
                      啟用
                    </label>
                    <div className="flex shrink-0 items-center gap-1 self-end sm:self-auto">
                      <button
                        type="button"
                        onClick={() => moveHop(id, -1)}
                        disabled={index === 0 || loading || saving}
                        aria-label={`上移 ${hop.label}`}
                        className="flex size-9 items-center justify-center rounded-md border border-border text-content-muted transition-colors hover:bg-surface-sunken hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-35"
                      >
                        <span aria-hidden="true" className="material-symbols-outlined text-lg">arrow_upward</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => moveHop(id, 1)}
                        disabled={index === order.length - 1 || loading || saving}
                        aria-label={`下移 ${hop.label}`}
                        className="flex size-9 items-center justify-center rounded-md border border-border text-content-muted transition-colors hover:bg-surface-sunken hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-35"
                      >
                        <span aria-hidden="true" className="material-symbols-outlined text-lg">arrow_downward</span>
                      </button>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <div className="mt-5 rounded-lg bg-surface-sunken px-4 py-5 text-sm text-content-muted" role="status">
              載入供應商設定後即可調整順序。
            </div>
          )}
        </section>

        <section className="rounded-xl border border-border bg-surface-raised p-5 md:p-6">
          <div>
            <h2 className="text-base font-semibold text-content">API 金鑰</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-content-muted">
              金鑰加密儲存在伺服器。頁面只顯示來源與遮罩提示，儲存後不會再顯示完整值。
            </p>
          </div>

          <div className="mt-5 divide-y divide-border border-y border-border">
            {CREDENTIALS.map(({ id, title, description }) => {
              const provider = providerStatus(id);
              const pendingAction = clearKeys.has(id)
                ? "將清除目前金鑰"
                : useEnvironmentKeys.has(id)
                  ? "將恢復使用部署環境金鑰"
                  : null;
              return (
                <div key={id} data-testid={`credential-${id}`} className="grid gap-4 py-4 md:grid-cols-[minmax(12rem,0.8fr)_minmax(16rem,1.2fr)_auto] md:items-center">
                  <div>
                    <label htmlFor={`decision-key-${id}`} className="text-sm font-medium text-content">{title}</label>
                    <p className="mt-1 text-xs leading-5 text-content-subtle">{description}</p>
                  </div>
                  <div className="min-w-0">
                    <input
                      id={`decision-key-${id}`}
                      type="password"
                      autoComplete="new-password"
                      maxLength={4096}
                      value={keys[id] ?? ""}
                      onChange={(event) => {
                        const value = event.target.value;
                        setKeys((current) => ({ ...current, [id]: value }));
                        setClearKeys((current) => {
                          const next = new Set(current);
                          next.delete(id);
                          return next;
                        });
                        setUseEnvironmentKeys((current) => {
                          const next = new Set(current);
                          next.delete(id);
                          return next;
                        });
                      }}
                      placeholder={provider?.credential_configured ? provider.credential_masked : "輸入 API key"}
                      disabled={!settings || loading || saving}
                      className="h-10 w-full rounded-md border border-border bg-surface px-3 text-sm text-content placeholder:text-content-subtle focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60"
                    />
                    <p className="mt-1 min-h-4 text-xs text-content-subtle" aria-live="polite">
                      {pendingAction ?? (provider?.credential_configured
                        ? `${provider.credential_source === "environment" ? "環境變數已設定" : "後台金鑰已設定"}${provider.credential_masked ? ` · ${provider.credential_masked}` : ""}`
                        : provider?.credential_required ? "尚未設定；此供應商會略過。" : "未設定；Clef 可不帶 key 呼叫。")}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 md:justify-end">
                    <button
                      type="button"
                      onClick={() => setCredentialAction(id, "clear")}
                      disabled={!provider?.credential_configured || saving || loading}
                      className="min-h-9 rounded-md px-3 text-xs text-content-muted transition-colors hover:bg-surface-sunken hover:text-content disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      清除金鑰
                    </button>
                    {provider?.credential_source === "admin" && (
                      <button
                        type="button"
                        onClick={() => setCredentialAction(id, "environment")}
                        disabled={saving || loading}
                        className="min-h-9 rounded-md px-3 text-xs text-content-muted transition-colors hover:bg-surface-sunken hover:text-content disabled:opacity-40"
                      >
                        使用部署預設
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <div className="flex flex-col-reverse gap-3 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-2xl text-xs leading-5 text-content-subtle">
            OpenAI Decisions 使用專用 Decisions API；模型依 OpenAI 目前支援設定為 gpt-6-luna。
          </p>
          <button
            type="button"
            onClick={() => void save()}
            disabled={!settings || loading || saving}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-primary px-5 text-sm font-medium text-white transition-colors hover:bg-primary/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-base">save</span>
            {saving ? "儲存中…" : "儲存設定"}
          </button>
        </div>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";

import StatusAlert from "../components/StatusAlert";
import { useAdminSubView } from "../hooks/useAdminSubView";
import { useBottomBarClearance } from "../hooks/useBottomBarClearance";
import { useNavigationGuard, useUnsavedChanges } from "../context/NavigationGuardContext";
import { handleTablistKeyDown } from "../utils/tablistKeys";
import {
  fetchModelProviderSettings,
  resetModelProviderHealth,
  saveModelProviderSettings,
  type HopHealth,
  type ModelCategory,
  type ModelProviderSettings,
  type ProviderCredential,
} from "../api/modelProviders";

const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  decision: "本地規則無法判斷時，依序詢問的決策供應商。每個有效答案會立即返回；連線、逾時、驗證或回應錯誤時才換下一個。",
  chat_llm: "產生回答的主對話模型。依序嘗試啟用的供應商；模型名稱留空時沿用部署設定的 LLM_FALLBACK_CHAIN。",
};

// 遮罩長得一樣（都是 ••••末四碼），要一眼看出這把 key 是 .env 的還是後台加密存的。
const SOURCE_BADGES: Record<ProviderCredential["source"], { label: string; className: string }> = {
  environment: { label: "來自 .env", className: "rounded bg-surface-sunken px-2 py-0.5 text-xs text-content-muted" },
  admin: { label: "後台已存（加密）", className: "rounded bg-primary/10 px-2 py-0.5 text-xs text-primary" },
  unreadable: { label: "無法解密", className: "rounded bg-danger/10 px-2 py-0.5 text-xs text-danger" },
  none: { label: "未設定", className: "rounded bg-surface-sunken px-2 py-0.5 text-xs text-content-subtle" },
};

// Brain 依用途分開記失敗（reason 後面帶「（decision_turn）」這類標註），標在狀態後面。
const PURPOSE_LABELS: Record<string, string> = {
  decision_turn: "每輪判斷",
  reference_media: "附圖選擇",
  memory_gate: "記憶判斷",
  recall_filter: "記憶篩選",
  asr_final_judge: "辨識定稿",
  language: "語言判斷",
  interrupt: "插話判斷",
  no_answer: "查無答案判斷",
  privacy: "個資偵測",
};

function healthLabel(health: HopHealth): string | null {
  const reason = health.reason ?? "";
  const purpose = reason.match(/（(.+)）$/)?.[1];
  const suffix = purpose ? `（${PURPOSE_LABELS[purpose] ?? purpose}）` : "";
  const auth = /^(auth|http_401|http_403)/.test(reason);
  if (health.status === "blocked") {
    return (auth ? "已跳過：金鑰無效，換金鑰後立即重試" : "已跳過，重開後重試") + suffix;
  }
  if (health.status === "cooling") {
    return `連續失敗，冷卻中，約 ${health.retry_in_seconds ?? 0} 秒後再試${suffix}`;
  }
  if (health.status === "degraded") return `剛失敗過，下一輪會再試${suffix}`;
  return null;
}

// 網址子頁 → 頁面內容；第一個是預設（/admin/model-providers）。
const PAGE_TABS = ["chat", "decision", "keys"] as const;
type PageTab = (typeof PAGE_TABS)[number];
const TAB_CATEGORY: Record<PageTab, string | null> = { chat: "chat_llm", decision: "decision", keys: null };
const TAB_LABELS: Record<PageTab, string> = { chat: "主對話模型", decision: "決策模型", keys: "API 金鑰" };

function tabClassName(active: boolean): string {
  return [
    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
    active
      ? "border border-border/60 bg-surface-raised text-content shadow-sm"
      : "text-content-muted hover:bg-surface-sunken hover:text-content",
  ].join(" ");
}

type PageNotice = { type: "success" | "error"; message: string } | null;

interface CategoryDraft {
  order: string[];
  enabled: Set<string>;
  models: Record<string, string>;
}

function draftFrom(category: ModelCategory): CategoryDraft {
  return {
    order: category.order,
    enabled: new Set(category.enabled),
    models: Object.fromEntries(
      category.providers.map((provider) => [provider.id, provider.model_override]),
    ),
  };
}

function draftChanged(draft: CategoryDraft, category: ModelCategory): boolean {
  const saved = draftFrom(category);
  const sameOrder = draft.order.join("\n") === saved.order.join("\n");
  const sameEnabled = draft.enabled.size === saved.enabled.size
    && [...draft.enabled].every((id) => saved.enabled.has(id));
  const sameModels = category.providers.every(
    (provider) => (draft.models[provider.id] ?? "").trim() === (saved.models[provider.id] ?? "").trim(),
  );
  return !(sameOrder && sameEnabled && sameModels);
}

const iconButton =
  "flex size-9 items-center justify-center rounded-md border border-border text-content-muted transition-colors hover:bg-surface-sunken hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-35";
const textInput =
  "h-10 w-full rounded-md border border-border bg-surface px-3 text-sm text-content placeholder:text-content-subtle focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60";
const quietButton =
  "min-h-9 rounded-md px-3 text-xs text-content-muted transition-colors hover:bg-surface-sunken hover:text-content disabled:cursor-not-allowed disabled:opacity-40";

export default function ModelProviders() {
  const [activeTab, setActiveTab] = useAdminSubView<PageTab>("ModelProviders", "chat", PAGE_TABS);
  const [settings, setSettings] = useState<ModelProviderSettings | null>(null);
  const [drafts, setDrafts] = useState<Record<string, CategoryDraft>>({});
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [clearKeys, setClearKeys] = useState<Set<string>>(new Set());
  const [useEnvironmentKeys, setUseEnvironmentKeys] = useState<Set<string>>(new Set());
  const [resetCategories, setResetCategories] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const saveBarRef = useRef<HTMLDivElement>(null);
  useBottomBarClearance(saveBarRef);
  const [resetting, setResetting] = useState<string | null>(null);
  const [notice, setNotice] = useState<PageNotice>(null);

  const apply = useCallback((result: ModelProviderSettings) => {
    setSettings(result);
    setDrafts(Object.fromEntries(result.categories.map((category) => [category.id, draftFrom(category)])));
    setKeys({});
    setClearKeys(new Set());
    setUseEnvironmentKeys(new Set());
    setResetCategories(new Set());
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setNotice(null);
    try {
      apply(await fetchModelProviderSettings());
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "無法載入模型供應商設定。",
      });
    } finally {
      setLoading(false);
    }
  }, [apply]);

  useEffect(() => {
    void load();
  }, [load]);

  function updateDraft(categoryId: string, change: (draft: CategoryDraft) => CategoryDraft) {
    setDrafts((current) => {
      const draft = current[categoryId];
      return draft ? { ...current, [categoryId]: change(draft) } : current;
    });
  }

  function moveHop(categoryId: string, id: string, offset: -1 | 1) {
    updateDraft(categoryId, (draft) => {
      const index = draft.order.indexOf(id);
      const destination = index + offset;
      if (index < 0 || destination < 0 || destination >= draft.order.length) return draft;
      const order = [...draft.order];
      [order[index], order[destination]] = [order[destination], order[index]];
      return { ...draft, order };
    });
  }

  function toggleHop(categoryId: string, id: string) {
    updateDraft(categoryId, (draft) => {
      const enabled = new Set(draft.enabled);
      if (enabled.has(id)) enabled.delete(id);
      else enabled.add(id);
      return { ...draft, enabled };
    });
  }

  async function save() {
    setSaving(true);
    setNotice(null);
    try {
      const credentials = Object.fromEntries(
        Object.entries(keys)
          .filter(([, value]) => Boolean(value.trim()))
          .map(([id, value]) => [id, value.trim()]),
      );
      // 只送有改的類別：沒動的維持原狀（還沒存過的就繼續照部署設定）。
      const changed = (settings?.categories ?? []).filter((category) => {
        const draft = drafts[category.id];
        return draft && !resetCategories.has(category.id) && draftChanged(draft, category);
      });
      const result = await saveModelProviderSettings({
        categories: Object.fromEntries(
          changed.map((category) => {
            const draft = drafts[category.id];
            return [category.id, {
              order: draft.order,
              enabled: draft.order.filter((hop) => draft.enabled.has(hop)),
              models: draft.models,
            }];
          }),
        ),
        reset_categories: [...resetCategories],
        credentials,
        clear_credentials: [...clearKeys],
        use_environment_credentials: [...useEnvironmentKeys],
      });
      apply(result);
      setNotice({
        type: "success",
        message: result.runtime_refreshed
          ? "模型供應商設定已儲存並立即生效。"
          : "模型供應商設定已儲存；Brain 暫時沒回應，約 10 秒內生效。",
      });
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "儲存模型供應商設定失敗。",
      });
    } finally {
      setSaving(false);
    }
  }

  function setCredentialAction(credentialId: string, action: "clear" | "environment") {
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

  function credentialStatus(credential: ProviderCredential): string {
    if (clearKeys.has(credential.id)) return "將清除目前金鑰";
    if (useEnvironmentKeys.has(credential.id)) {
      return `儲存後刪除後台金鑰，改用伺服器的 ${credential.environment_variable}`;
    }
    if (credential.source === "unreadable") {
      return credential.configured
        ? `後台金鑰無法解密，暫用環境變數 · ${credential.masked}；請重新輸入`
        : "後台金鑰無法解密，環境變數也沒有；請重新輸入";
    }
    if (credential.configured) {
      const source = credential.source === "environment" ? "環境變數已設定" : "後台金鑰已設定";
      return credential.masked ? `${source} · ${credential.masked}` : source;
    }
    return credential.required ? "尚未設定；用到它的供應商會略過。" : "未設定；可不帶 key 呼叫。";
  }

  const busy = loading || saving || resetting !== null;

  async function resetHealth(category: string, hop: string) {
    setResetting(`${category}:${hop}`);
    setNotice(null);
    try {
      // 只換狀態，不套用到草稿：重置不該把還沒存的修改洗掉。
      setSettings(await resetModelProviderHealth({ category, hop }));
      setNotice({ type: "success", message: "已重置，下一輪會照順序重新嘗試這一站。" });
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "重置失敗。",
      });
    } finally {
      setResetting(null);
    }
  }

  function tabHasPendingChanges(tab: PageTab): boolean {
    const categoryId = TAB_CATEGORY[tab];
    if (categoryId === null) {
      return clearKeys.size > 0 || useEnvironmentKeys.size > 0
        || Object.values(keys).some((value) => value.trim());
    }
    const category = settings?.categories.find((item) => item.id === categoryId);
    const draft = drafts[categoryId];
    return resetCategories.has(categoryId) || Boolean(category && draft && draftChanged(draft, category));
  }

  // 任一分頁有未儲存的修改，離開頁面與重新載入都要先確認，不能默默把草稿蓋掉。
  const hasPendingChanges = PAGE_TABS.some((tab) => tabHasPendingChanges(tab));
  useUnsavedChanges("model-providers", hasPendingChanges, "模型供應商設定");
  const { requestNavigation } = useNavigationGuard();

  return (
    <div className="page-scroll">
      <header className="page-header">
        <div className="page-heading">
          <h1 className="page-title">模型供應商</h1>
          <p className="page-subtitle">全站各類模型使用哪幾家、優先順序與 API 金鑰。只有 ROOT 能修改。</p>
        </div>
        <button
          type="button"
          onClick={() => requestNavigation(() => void load())}
          disabled={busy}
          className="btn btn-ghost shrink-0"
        >
          {loading ? "載入中…" : "重新載入"}
        </button>
      </header>

      <div className="mx-auto max-w-5xl space-y-6 p-6 md:p-8">
        {notice && <StatusAlert type={notice.type} message={notice.message} />}

        <div
          role="tablist"
          aria-label="模型供應商分類"
          className="flex w-fit max-w-full flex-wrap rounded-lg border border-border/50 bg-surface-sunken p-1"
          onKeyDown={(event) => handleTablistKeyDown(event, PAGE_TABS, activeTab)}
        >
          {PAGE_TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              id={`model-providers-${tab}-tab`}
              aria-controls="model-providers-panel"
              aria-selected={activeTab === tab}
              tabIndex={activeTab === tab ? 0 : -1}
              onClick={() => setActiveTab(tab)}
              className={tabClassName(activeTab === tab)}
            >
              {TAB_LABELS[tab]}
              {tabHasPendingChanges(tab) && (
                <span className="size-1.5 rounded-full bg-primary" aria-label="有未儲存的修改" />
              )}
            </button>
          ))}
        </div>

        <div id="model-providers-panel" role="tabpanel" aria-labelledby={`model-providers-${activeTab}-tab`} className="space-y-6">
        {loading && !settings ? (
          <div className="space-y-3" aria-label="正在載入供應商設定">
            {[0, 1, 2, 3].map((row) => (
              <div key={row} className="h-20 animate-pulse rounded-lg bg-surface-sunken" />
            ))}
          </div>
        ) : !settings ? (
          <div className="rounded-lg bg-surface-sunken px-4 py-5 text-sm text-content-muted" role="status">
            載入供應商設定後即可調整。
          </div>
        ) : (
          <>
            {settings.categories.filter((category) => category.id === TAB_CATEGORY[activeTab]).map((category) => {
              const draft = drafts[category.id];
              if (!draft) return null;
              const hops = new Map(category.providers.map((provider) => [provider.id, provider]));
              return (
                <section
                  key={category.id}
                  data-testid={`category-${category.id}`}
                  className="rounded-xl border border-border bg-surface-raised p-5 md:p-6"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                      <h2 className="text-base font-semibold text-content">{category.label}</h2>
                      <p className="mt-1 max-w-3xl text-sm leading-6 text-content-muted">
                        {CATEGORY_DESCRIPTIONS[category.id]}
                      </p>
                      {resetCategories.has(category.id) ? (
                        <p className="mt-1 text-xs text-content-subtle" aria-live="polite">
                          儲存後改回部署設定，下面的調整不會存。
                        </p>
                      ) : !category.configured && (
                        <p className="mt-1 text-xs text-content-subtle">
                          尚未在後台儲存過，目前照部署設定運作；調整後儲存才會改用後台設定。
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col items-start gap-1 sm:items-end">
                      {category.configured && (
                        <button
                          type="button"
                          onClick={() => setResetCategories((current) => {
                            const next = new Set(current);
                            if (next.has(category.id)) next.delete(category.id);
                            else next.add(category.id);
                            return next;
                          })}
                          disabled={busy}
                          aria-pressed={resetCategories.has(category.id)}
                          className={quietButton}
                        >
                          {resetCategories.has(category.id) ? "取消改回" : "改回部署設定"}
                        </button>
                      )}
                      <span className="text-xs text-content-subtle">使用 ↑ ↓ 調整優先順序</span>
                    </div>
                  </div>

                  <ol className="mt-5 divide-y divide-border border-y border-border">
                    {draft.order.map((id, index) => {
                      const hop = hops.get(id);
                      if (!hop) return null;
                      const active = draft.enabled.has(id);
                      return (
                        <li
                          key={id}
                          data-testid={`provider-${category.id}-${id}`}
                          className={`flex flex-col gap-4 py-4 sm:flex-row sm:items-center sm:gap-5 ${active ? "" : "opacity-65"}`}
                        >
                          <span className="w-7 shrink-0 text-center font-mono text-sm tabular-nums text-content-subtle" aria-label={`優先順序 ${index + 1}`}>
                            {index + 1}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="font-medium text-content">{hop.label}</h3>
                              {!active && <span className="rounded bg-surface-sunken px-2 py-0.5 text-xs text-content-subtle">已停用</span>}
                              {active && healthLabel(hop.health) && (
                                <>
                                  <span
                                    role="status"
                                    className="rounded bg-danger/10 px-2 py-0.5 text-xs text-danger"
                                  >
                                    {healthLabel(hop.health)}
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => void resetHealth(category.id, hop.id)}
                                    disabled={busy}
                                    aria-label={`重置 ${category.label} ${hop.label} 的失敗紀錄`}
                                    className={quietButton}
                                  >
                                    {resetting === `${category.id}:${hop.id}` ? "重置中…" : "重置"}
                                  </button>
                                </>
                              )}
                            </div>
                            <p className="mt-1 break-all font-mono text-xs text-content-muted">{hop.endpoint}</p>
                            {category.model_editable ? (
                              <label className="mt-2 flex max-w-md items-center gap-2 text-xs text-content-subtle">
                                <span className="shrink-0">模型</span>
                                <input
                                  type="text"
                                  maxLength={128}
                                  value={draft.models[id] ?? ""}
                                  onChange={(event) => {
                                    const value = event.target.value;
                                    updateDraft(category.id, (current) => ({
                                      ...current,
                                      models: { ...current.models, [id]: value },
                                    }));
                                  }}
                                  placeholder={hop.default_model}
                                  aria-label={`${category.label} ${hop.label} 模型`}
                                  disabled={busy}
                                  className={`${textInput} h-9 font-mono text-xs`}
                                />
                              </label>
                            ) : (
                              <p className="mt-1 text-xs text-content-subtle">模型：{hop.model}</p>
                            )}
                          </div>
                          <label className="flex min-h-10 shrink-0 items-center gap-2 text-sm text-content-muted">
                            <input
                              type="checkbox"
                              checked={active}
                              onChange={() => toggleHop(category.id, id)}
                              aria-label={`啟用 ${category.label} ${hop.label}`}
                              className="size-4 accent-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                            />
                            啟用
                          </label>
                          <div className="flex shrink-0 items-center gap-1 self-end sm:self-auto">
                            <button
                              type="button"
                              onClick={() => moveHop(category.id, id, -1)}
                              disabled={index === 0 || busy}
                              aria-label={`上移 ${category.label} ${hop.label}`}
                              className={iconButton}
                            >
                              <span aria-hidden="true" className="material-symbols-outlined text-lg">arrow_upward</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => moveHop(category.id, id, 1)}
                              disabled={index === draft.order.length - 1 || busy}
                              aria-label={`下移 ${category.label} ${hop.label}`}
                              className={iconButton}
                            >
                              <span aria-hidden="true" className="material-symbols-outlined text-lg">arrow_downward</span>
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                </section>
              );
            })}

            {activeTab === "keys" && <section className="rounded-xl border border-border bg-surface-raised p-5 md:p-6">
              <div>
                <h2 className="text-base font-semibold text-content">API 金鑰</h2>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-content-muted">
                  每家一把，所有用到它的類別共用。金鑰加密儲存在伺服器，頁面只顯示來源與遮罩提示。
                </p>
              </div>

              <div className="mt-5 divide-y divide-border border-y border-border">
                {settings.credentials.map((credential) => (
                  <div
                    key={credential.id}
                    data-testid={`credential-${credential.id}`}
                    className="grid gap-4 py-4 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_auto] md:items-center"
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <label htmlFor={`provider-key-${credential.id}`} className="text-sm font-medium text-content">
                          {credential.label} API key
                        </label>
                        <span className={SOURCE_BADGES[credential.source].className}>
                          {SOURCE_BADGES[credential.source].label}
                        </span>
                      </div>
                      <p className="mt-1 text-xs leading-5 text-content-subtle">
                        用於{credential.used_by.join("、")}；未填時沿用部署環境的 {credential.environment_variable}。
                      </p>
                    </div>
                    <div className="min-w-0">
                      <input
                        id={`provider-key-${credential.id}`}
                        type="password"
                        autoComplete="new-password"
                        maxLength={4096}
                        value={keys[credential.id] ?? ""}
                        onChange={(event) => {
                          const value = event.target.value;
                          setKeys((current) => ({ ...current, [credential.id]: value }));
                          setClearKeys((current) => {
                            const next = new Set(current);
                            next.delete(credential.id);
                            return next;
                          });
                          setUseEnvironmentKeys((current) => {
                            const next = new Set(current);
                            next.delete(credential.id);
                            return next;
                          });
                        }}
                        placeholder={credential.configured ? credential.masked : "輸入 API key"}
                        disabled={busy}
                        className={textInput}
                      />
                      <p className="mt-1 min-h-4 text-xs text-content-subtle" aria-live="polite">
                        {credentialStatus(credential)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 md:justify-end">
                      <button
                        type="button"
                        onClick={() => setCredentialAction(credential.id, "clear")}
                        disabled={!credential.configured || busy}
                        className={quietButton}
                      >
                        清除金鑰
                      </button>
                      {(credential.source === "admin" || credential.source === "unreadable") && (
                        <button
                          type="button"
                          onClick={() => setCredentialAction(credential.id, "environment")}
                          disabled={busy}
                          title={`儲存後刪除後台加密存的這把金鑰，改用伺服器部署設定的 ${credential.environment_variable}`}
                          className={quietButton}
                        >
                          移除後台金鑰，改用 .env
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>}
          </>
        )}
        </div>

        {/* 金鑰分頁有六組，存檔鈕放最底會被推出視窗；固定在捲動區底部。 */}
        <div ref={saveBarRef} className="sticky bottom-0 z-10 -mx-6 flex justify-end border-t border-border bg-surface/95 px-6 py-4 backdrop-blur-md md:-mx-8 md:px-8">
          <button
            type="button"
            onClick={() => void save()}
            disabled={!settings || busy}
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

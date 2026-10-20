import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchAccountAccessOptions,
  fetchAdminScope,
  updateAdminScope,
  type Account,
  type AccountAccessOption,
  type AccountAccessOptions,
  type AdminScopeResources,
} from "../../api/auth";
import { useAuth } from "../../context/AuthContext";
import { groupAccessOptions } from "./accountAccessGroups";
import GroupedChecklist from "./GroupedChecklist";

type ScopeKey = keyof AdminScopeResources;

const EMPTY_RESOURCES: AdminScopeResources = {
  projects: [],
  avatar_characters: [],
  custom_voices: [],
  avatar_mascots: [],
  avatar_backgrounds: [],
};

const GROUPS: Array<{ key: ScopeKey; title: string }> = [
  { key: "projects", title: "知識庫專案" },
  { key: "avatar_characters", title: "虛擬人物" },
  { key: "avatar_mascots", title: "VRM" },
  { key: "custom_voices", title: "自訂聲音" },
  { key: "avatar_backgrounds", title: "舞台背景" },
];

interface AdminScopePanelProps {
  account: Account;
  onCancel: () => void;
  onSaved: () => void;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function optionsFor(
  options: AccountAccessOptions | null,
  key: ScopeKey,
): AccountAccessOption[] {
  if (!options) return [];
  return options[key] ?? [];
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
  const [selection, setSelection] = useState<AdminScopeResources>(EMPTY_RESOURCES);
  const [loading, setLoading] = useState(true);
  // 讀到目前的上限才准儲存：讀失敗時表單裡是預設的「不設限」，ROOT 一按儲存
  // 就會把管理員的限制整個解掉。
  const [loaded, setLoaded] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoaded(false);
    setError(null);
    Promise.all([fetchAccountAccessOptions(), fetchAdminScope(account.id)])
      .then(([fetchedOptions, scope]) => {
        if (cancelled) return;
        setOptions(fetchedOptions);
        setScoped(scope.scoped);
        setSelection({ ...EMPTY_RESOURCES, ...scope.resources });
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

  const toggleAll = useCallback((key: ScopeKey, ids: string[]) => {
    setSelection((current) => {
      const values = current[key] ?? [];
      const allSelected = ids.length > 0
        && ids.every((id) => values.includes(id));
      return {
        ...current,
        [key]: allSelected
          ? values.filter((value) => !ids.includes(value))
          : Array.from(new Set([...values, ...ids])),
      };
    });
  }, []);

  const setSome = useCallback((key: ScopeKey, ids: string[], selected: boolean) => {
    setSelection((current) => {
      const values = current[key] ?? [];
      return {
        ...current,
        [key]: selected
          ? Array.from(new Set([...values, ...ids]))
          : values.filter((value) => !ids.includes(value)),
      };
    });
  }, []);

  const toggle = useCallback((key: ScopeKey, id: string) => {
    setSelection((current) => {
      const values = current[key] ?? [];
      const next = values.includes(id)
        ? values.filter((value) => value !== id)
        : [...values, id];
      return { ...current, [key]: next };
    });
  }, []);

  const selectedCount = useMemo(
    () => GROUPS.reduce((total, group) => total + (selection[group.key]?.length ?? 0), 0),
    [selection],
  );

  const statusText = useMemo(() => {
    if (loading) return "載入中…";
    if (selectedCount === 0) return "已選 0 項（這位管理員將看不到任何資源）";
    return `已選 ${selectedCount} 項`;
  }, [loading, selectedCount]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await updateAdminScope(account.id, {
        scoped,
        resources: scoped ? selection : EMPTY_RESOURCES,
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

      <label className="mt-4 flex cursor-pointer items-start gap-3">
        <input
          className="mt-1 h-4 w-4 accent-primary"
          type="checkbox"
          checked={scoped}
          disabled={!canUnrestrict}
          onChange={(event) => setScoped(event.target.checked)}
        />
        <span>
          <span className="block text-sm font-semibold">限制可用資源</span>
          <span className="mt-1 block text-xs leading-5 text-content-muted">
            {canUnrestrict
              ? "不勾選代表不設限，這位管理員維持看得到全部資源。勾選後只有下方選取的項目對他可見，縮小範圍會一併撤銷他先前發出、如今已超出上限的授權。"
              : "你自己的範圍有限，指派出去的上限只能是其中的子集，因此無法取消限制。縮小範圍會一併撤銷他先前發出、如今已超出上限的授權。"}
          </span>
        </span>
      </label>

      {scoped && (
        <>
          <p className="mt-4 text-xs text-content-muted" role="status">
            {statusText}
          </p>
          <div className="mt-2 grid grid-cols-1 gap-0 md:grid-cols-2 xl:grid-cols-3">
            {GROUPS.map((group) => {
              const groupOptions = optionsFor(options, group.key);
                const groupIds = groupOptions.map((option) => option.id);
                const selectedHere = selection[group.key] ?? [];
                const allSelected = groupIds.length > 0
                  && groupIds.every((id) => selectedHere.includes(id));
                return (
                <div key={group.key} className="border-t border-border px-1 py-4">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="text-sm font-semibold">{group.title}</h4>
                    <button
                      className="btn btn-ghost px-2 py-1 text-xs"
                      type="button"
                      onClick={() => toggleAll(group.key, groupIds)}
                      disabled={groupIds.length === 0}
                    >
                      {allSelected ? "全部不選" : "全選"}
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-content-subtle">
                    已選 {selectedHere.length} / {groupIds.length}
                  </p>
                  <GroupedChecklist
                    sections={groupAccessOptions(group.key, groupOptions, options?.projects ?? [])}
                    isSelected={(option) => (selection[group.key] ?? []).includes(option.id)}
                    onToggle={(option) => toggle(group.key, option.id)}
                    onSetAll={(targets, selected) => setSome(group.key, targets.map((option) => option.id), selected)}
                    loading={loading}
                    emptyText="目前沒有可指派項目"
                    searchLabel={`搜尋${group.title}`}
                  />
                </div>
              );
            })}
          </div>
        </>
      )}

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

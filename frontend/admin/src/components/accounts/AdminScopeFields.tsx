import type {
  AccountAccessOption,
  AccountAccessOptions,
  AdminScopeResources,
} from "../../api/auth";
import { groupAccessOptions } from "./accountAccessGroups";
import GroupedChecklist from "./GroupedChecklist";

export type ScopeKey = keyof AdminScopeResources;

export const EMPTY_SCOPE_RESOURCES: AdminScopeResources = {
  projects: [],
  avatar_characters: [],
  custom_voices: [],
  avatar_mascots: [],
  avatar_backgrounds: [],
  asr_engines: [],
};

export const SCOPE_GROUPS: Array<{ key: ScopeKey; title: string }> = [
  { key: "projects", title: "知識庫專案" },
  { key: "avatar_characters", title: "虛擬人物" },
  { key: "avatar_mascots", title: "小助理" },
  { key: "custom_voices", title: "自訂聲音" },
  { key: "avatar_backgrounds", title: "舞台背景" },
  { key: "asr_engines", title: "語音辨識引擎" },
];

function optionsFor(options: AccountAccessOptions | null, key: ScopeKey): AccountAccessOption[] {
  if (!options) return [];
  return options[key] ?? [];
}

export function scopeSelectedCount(selection: AdminScopeResources): number {
  return SCOPE_GROUPS.reduce((total, group) => total + (selection[group.key]?.length ?? 0), 0);
}

interface AdminScopeFieldsProps {
  options: AccountAccessOptions | null;
  loading: boolean;
  scoped: boolean;
  /** 只有 ROOT 給得出「不設限」；受限 admin 指派出去的上限只能是子集。 */
  canUnrestrict: boolean;
  selection: AdminScopeResources;
  onScopedChange: (scoped: boolean) => void;
  onSelectionChange: (next: AdminScopeResources) => void;
}

/** 管理員「資源上限」的勾選欄位；建立管理員與事後編輯共用。 */
export default function AdminScopeFields({
  options,
  loading,
  scoped,
  canUnrestrict,
  selection,
  onScopedChange,
  onSelectionChange,
}: AdminScopeFieldsProps) {
  const selectedCount = scopeSelectedCount(selection);
  const statusText = loading
    ? "載入中…"
    : selectedCount === 0
      ? "已選 0 項（這位管理員將看不到任何資源）"
      : `已選 ${selectedCount} 項`;

  function setSome(key: ScopeKey, ids: string[], selected: boolean) {
    const values = selection[key] ?? [];
    onSelectionChange({
      ...selection,
      [key]: selected
        ? Array.from(new Set([...values, ...ids]))
        : values.filter((value) => !ids.includes(value)),
    });
  }

  return (
    <>
      <label className="mt-4 flex cursor-pointer items-start gap-3">
        <input
          className="mt-1 h-4 w-4 accent-primary"
          type="checkbox"
          checked={scoped}
          disabled={!canUnrestrict}
          onChange={(event) => onScopedChange(event.target.checked)}
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
            {SCOPE_GROUPS.map((group) => {
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
                      onClick={() => setSome(group.key, groupIds, !allSelected)}
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
                    isSelected={(option) => selectedHere.includes(option.id)}
                    onToggle={(option) => setSome(group.key, [option.id], !selectedHere.includes(option.id))}
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
    </>
  );
}

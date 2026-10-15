import { useId, useMemo, useState } from "react";

import type { AccountRole } from "../../api/auth";
import { KIND_LABELS, ROLE_LABELS, type ResourceLayer } from "./buildAccessGraph";
import {
  ACCOUNT_ROLES,
  ACCOUNT_TYPE_LABELS,
  ACCOUNT_TYPES,
  RELATION_KINDS,
  RELATION_LABELS,
  RESOURCE_LAYERS,
  activeFilters,
  clearFilters,
  type AccessGraphFilters,
  type AccountType,
} from "./filterAccessGraph";
import FocusPicker, { type PickerGroup } from "./FocusPicker";
import { LineSymbol, NodeSymbol } from "./graphSymbols";

export interface FilterCounts {
  layers: Record<ResourceLayer, number>;
  roles: Record<AccountRole, number>;
  /** temporary 為 null：讀不到臨時帳號批次。 */
  accountTypes: { formal: number; temporary: number | null };
  disabled: number;
}

interface AccessGraphFilterBarProps {
  filters: AccessGraphFilters;
  onChange: (filters: AccessGraphFilters) => void;
  labels: Map<string, string>;
  projectGroups: PickerGroup[];
  resourceGroups: PickerGroup[];
  counts: FilterCounts | null;
  search: React.ReactNode;
  actions: React.ReactNode;
}

const toggleChipClass = (active: boolean) =>
  `inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 ${
    active
      ? "border-primary/40 bg-primary/10 text-content hover:bg-primary/15"
      : "border-border bg-surface-raised text-content-subtle hover:border-border-strong hover:text-content [&>svg]:opacity-40"
  }`;

function toggled<T>(list: readonly T[], item: T): T[] {
  return list.includes(item) ? list.filter((value) => value !== item) : [...list, item];
}

function Count({ value }: { value: number | string }) {
  return <span className="tabular-nums text-content-muted">{value}</span>;
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="flex flex-wrap items-center gap-1.5">
      <span id={id} className="w-full text-xs font-medium text-content-subtle sm:mr-1 sm:w-auto">
        {label}
      </span>
      {children}
    </div>
  );
}

const Divider = () => <span aria-hidden="true" className="mx-1 h-4 w-px bg-border" />;

const ROLE_SYMBOL = { root: "root", admin: "admin", user: "user" } as const;

export default function AccessGraphFilterBar({
  filters,
  onChange,
  labels,
  projectGroups,
  resourceGroups,
  counts,
  search,
  actions,
}: AccessGraphFilterBarProps) {
  const [open, setOpen] = useState(false);
  const groupsId = useId();
  const active = useMemo(() => activeFilters(filters, labels), [filters, labels]);
  const temporaryCount = counts?.accountTypes.temporary;

  const set = (patch: Partial<AccessGraphFilters>) => onChange({ ...filters, ...patch });

  return (
    <section aria-label="篩選" className="flex flex-col gap-3 px-4 pb-4 sm:px-6 lg:px-8">
      <div className="relative flex flex-wrap items-center gap-2">
        {search}
        <FocusPicker
          label="專案"
          description="只看能存取所選專案的帳號（選多個時任一個即可）。ROOT 與不受限管理員能存取全部，一律保留。"
          groups={projectGroups}
          selected={filters.projects}
          onChange={(projects) => set({ projects })}
        />
        <FocusPicker
          label="資源"
          description="只看有權使用所選人物、聲音或辨識引擎的帳號與他們的專案。同類選多個是任一個，跨類是都要。"
          groups={resourceGroups}
          selected={filters.resources}
          onChange={(resources) => set({ resources })}
        />
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-raised px-3 py-1.5 text-sm text-content hover:border-border-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:hidden"
          aria-expanded={open}
          aria-controls={groupsId}
          onClick={() => setOpen((value) => !value)}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">tune</span>
          更多條件
        </button>
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </div>

      <div
        id={groupsId}
        className={`${open ? "flex" : "hidden"} flex-col gap-3 rounded-lg border border-border bg-surface-sunken/60 p-3 sm:flex sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-6 sm:gap-y-2 sm:border-0 sm:bg-transparent sm:p-0`}
      >
        <Group label="帳號">
          {ACCOUNT_ROLES.map((role) => (
            <button
              key={role}
              type="button"
              className={toggleChipClass(filters.roles.includes(role))}
              aria-pressed={filters.roles.includes(role)}
              onClick={() => set({ roles: toggled(filters.roles, role) })}
            >
              <NodeSymbol kind={ROLE_SYMBOL[role]} />
              {ROLE_LABELS[role]}
              {counts && <Count value={counts.roles[role]} />}
            </button>
          ))}
          <Divider />
          {ACCOUNT_TYPES.map((type: AccountType) => {
            const unavailable = type === "temporary" && (temporaryCount === null || temporaryCount === 0);
            return (
              <button
                key={type}
                type="button"
                className={toggleChipClass(filters.accountTypes.includes(type))}
                aria-pressed={filters.accountTypes.includes(type)}
                disabled={Boolean(counts) && unavailable}
                title={type === "temporary" && temporaryCount === null ? "讀不到臨時帳號" : undefined}
                onClick={() => set({ accountTypes: toggled(filters.accountTypes, type) })}
              >
                <NodeSymbol kind={type === "temporary" ? "temporary" : "user"} />
                {ACCOUNT_TYPE_LABELS[type]}
                {counts && (
                  <Count
                    value={
                      type === "formal"
                        ? counts.accountTypes.formal
                        : temporaryCount === null
                          ? "—"
                          : `${temporaryCount} 批`
                    }
                  />
                )}
              </button>
            );
          })}
          <Divider />
          <button
            type="button"
            className={toggleChipClass(filters.includeDisabled)}
            aria-pressed={filters.includeDisabled}
            disabled={Boolean(counts) && counts?.disabled === 0}
            onClick={() => set({ includeDisabled: !filters.includeDisabled })}
          >
            停用帳號
            {counts && <Count value={counts.disabled} />}
          </button>
        </Group>

        <Group label="連線">
          {RELATION_KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              className={toggleChipClass(filters.relations.includes(kind))}
              aria-pressed={filters.relations.includes(kind)}
              onClick={() => set({ relations: toggled(filters.relations, kind) })}
            >
              <LineSymbol kind={kind} />
              {RELATION_LABELS[kind]}
            </button>
          ))}
        </Group>

        <Group label="圖層">
          {RESOURCE_LAYERS.map((layer) => (
            <button
              key={layer}
              type="button"
              className={toggleChipClass(filters.layers.includes(layer))}
              aria-pressed={filters.layers.includes(layer)}
              onClick={() => set({ layers: toggled(filters.layers, layer) })}
            >
              <NodeSymbol kind={layer} />
              {KIND_LABELS[layer]}
              {counts && <Count value={counts.layers[layer]} />}
            </button>
          ))}
        </Group>
      </div>

      {active.length > 0 && (
        <div role="region" aria-label="目前的篩選" className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs font-semibold tabular-nums text-content">
            {active.length} 個篩選
          </span>
          {active.map((item) => (
            <span
              key={item.key}
              className="inline-flex max-w-full items-center gap-0.5 rounded-full border border-primary/30 bg-primary/10 py-0.5 pl-2.5 pr-0.5 text-xs text-content"
            >
              <span className="min-w-0 truncate">{item.label}</span>
              <button
                type="button"
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-content-muted hover:bg-primary/15 hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                aria-label={`移除篩選：${item.label}`}
                onClick={() => onChange(item.remove(filters))}
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[0.875rem]">close</span>
              </button>
            </span>
          ))}
          <button
            type="button"
            className="ml-1 rounded px-1.5 py-0.5 text-xs font-medium text-primary underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
            onClick={() => onChange(clearFilters(filters))}
          >
            清除全部
          </button>
        </div>
      )}
    </section>
  );
}

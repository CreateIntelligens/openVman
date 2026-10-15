import { useState } from "react";

import { RELATION_KINDS, RELATION_LABELS, type RelationKind } from "./filterAccessGraph";
import { LineSymbol, NodeSymbol, type SymbolKey } from "./graphSymbols";

const ITEMS: Array<{ key: SymbolKey; label: string }> = [
  { key: "project", label: "專案" },
  { key: "root", label: "ROOT" },
  { key: "admin", label: "管理員" },
  { key: "user", label: "一般帳號" },
  { key: "temporary", label: "臨時帳號（一批）" },
  { key: "character", label: "人物" },
  { key: "voice", label: "聲音" },
  { key: "asr", label: "辨識引擎" },
];

function startsOpen(): boolean {
  // 手機寬度下圖例會蓋掉半張圖，預設收起來。
  try {
    return window.matchMedia("(min-width: 40rem)").matches;
  } catch {
    return true;
  }
}

interface AccessGraphLegendProps {
  /** 被篩選關掉的圖例項目，淡化並註明，讓圖例跟畫面上看到的一致。 */
  muted?: ReadonlySet<SymbolKey | RelationKind>;
}

function itemClass(muted: boolean): string {
  return `flex items-center gap-1.5 whitespace-nowrap ${muted ? "opacity-40 line-through" : ""}`;
}

export default function AccessGraphLegend({ muted = new Set() }: AccessGraphLegendProps) {
  const [open] = useState(startsOpen);
  return (
    <details
      open={open}
      className="group absolute bottom-3 left-3 max-w-[calc(100%-1.5rem)] rounded-md border border-border bg-surface-raised/90 text-xs text-content-muted shadow-sm backdrop-blur"
    >
      <summary className="cursor-pointer select-none list-none px-3 py-1.5 font-medium text-content-subtle hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary [&::-webkit-details-marker]:hidden">
        圖例
        <span aria-hidden="true" className="ml-1 inline-block transition-transform group-open:rotate-180">▾</span>
      </summary>
      <div className="px-3 pb-2">
        <ul className="flex flex-wrap gap-x-3 gap-y-1">
          {ITEMS.map((item) => (
            <li
              key={item.key}
              className={itemClass(muted.has(item.key))}
              title={muted.has(item.key) ? "目前被篩選隱藏" : undefined}
            >
              <NodeSymbol kind={item.key} />
              {item.label}
            </li>
          ))}
        </ul>
        <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {RELATION_KINDS.map((kind) => (
            <li
              key={kind}
              className={itemClass(muted.has(kind))}
              title={muted.has(kind) ? "目前被篩選隱藏" : undefined}
            >
              <LineSymbol kind={kind} />
              {RELATION_LABELS[kind]}
            </li>
          ))}
          <li className="flex items-center gap-1.5 whitespace-nowrap">
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden="true">
              <circle cx={8} cy={8} r={5} className="fill-surface-raised stroke-content-muted" strokeWidth={1.2} strokeDasharray="2 1.5" />
            </svg>
            停用／過期／不在可見清單
          </li>
          <li className="flex items-center gap-1.5 whitespace-nowrap">
            <span className="font-medium text-info">中·台</span>
            專案的語言分流（只有中文不標）
          </li>
        </ul>
        <p className="mt-1">內圈專案・中圈帳號・外圈人物／聲音／辨識引擎</p>
      </div>
    </details>
  );
}

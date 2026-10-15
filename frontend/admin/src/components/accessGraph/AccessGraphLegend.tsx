import { useState } from "react";

const ITEMS: Array<{ label: string; symbol: React.ReactNode }> = [
  { label: "專案", symbol: <rect x={2} y={2} width={12} height={12} rx={3} className="fill-primary" /> },
  { label: "ROOT", symbol: <circle cx={8} cy={8} r={5.5} className="fill-content stroke-primary" strokeWidth={1.5} /> },
  { label: "管理員", symbol: <circle cx={8} cy={8} r={5} className="fill-info" /> },
  { label: "一般帳號", symbol: <circle cx={8} cy={8} r={5} className="fill-surface-raised stroke-content-muted" strokeWidth={1.2} /> },
  { label: "臨時帳號（一批）", symbol: <path d="M5,2.5 L11,2.5 L14,8 L11,13.5 L5,13.5 L2,8Z" className="fill-surface-raised stroke-info" strokeWidth={1.2} /> },
  { label: "人物", symbol: <path d="M8,2 L14,8 L8,14 L2,8Z" className="fill-success" /> },
  { label: "聲音", symbol: <circle cx={8} cy={8} r={3.5} className="fill-warn" /> },
  { label: "辨識引擎", symbol: <path d="M8,2 L14,13 L2,13Z" className="fill-content-subtle" /> },
];

const LINES: Array<{ label: string; className: string; width: number; dash?: string }> = [
  { label: "授權", className: "stroke-content-subtle", width: 1.2 },
  { label: "預設", className: "stroke-primary", width: 2.6 },
  { label: "管理範圍", className: "stroke-info", width: 1.2, dash: "4 3" },
];

function startsOpen(): boolean {
  // 手機寬度下圖例會蓋掉半張圖，預設收起來。
  try {
    return window.matchMedia("(min-width: 40rem)").matches;
  } catch {
    return true;
  }
}

export default function AccessGraphLegend() {
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
          <li key={item.label} className="flex items-center gap-1.5 whitespace-nowrap">
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden="true">{item.symbol}</svg>
            {item.label}
          </li>
        ))}
      </ul>
      <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
        {LINES.map((line) => (
          <li key={line.label} className="flex items-center gap-1.5 whitespace-nowrap">
            <svg viewBox="0 0 24 8" className="h-2 w-6" aria-hidden="true">
              <line x1={1} y1={4} x2={23} y2={4} className={line.className} strokeWidth={line.width} strokeDasharray={line.dash} />
            </svg>
            {line.label}
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

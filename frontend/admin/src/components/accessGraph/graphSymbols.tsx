import type { RelationKind } from "./filterAccessGraph";

export type SymbolKey =
  | "project"
  | "root"
  | "admin"
  | "user"
  | "temporary"
  | "character"
  | "voice"
  | "asr";

// 跟畫布上 NodeShape 的形狀、顏色一致；圖例與篩選鈕共用，兩邊才不會說不一樣的話。
const NODE_SYMBOLS: Record<SymbolKey, React.ReactNode> = {
  project: <rect x={2} y={2} width={12} height={12} rx={3} className="fill-primary" />,
  root: <circle cx={8} cy={8} r={5.5} className="fill-content stroke-primary" strokeWidth={1.5} />,
  admin: <circle cx={8} cy={8} r={5} className="fill-info" />,
  user: <circle cx={8} cy={8} r={5} className="fill-surface-raised stroke-content-muted" strokeWidth={1.2} />,
  temporary: (
    <path d="M5,2.5 L11,2.5 L14,8 L11,13.5 L5,13.5 L2,8Z" className="fill-surface-raised stroke-info" strokeWidth={1.2} />
  ),
  character: <path d="M8,2 L14,8 L8,14 L2,8Z" className="fill-success" />,
  voice: <circle cx={8} cy={8} r={3.5} className="fill-warn" />,
  asr: <path d="M8,2 L14,13 L2,13Z" className="fill-content-subtle" />,
};

const LINE_STYLES: Record<RelationKind, { className: string; width: number; dash?: string }> = {
  grant: { className: "stroke-content-subtle", width: 1.2 },
  default: { className: "stroke-primary", width: 2.6 },
  scope: { className: "stroke-info", width: 1.2, dash: "4 3" },
};

export function NodeSymbol({ kind }: { kind: SymbolKey }) {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 shrink-0" aria-hidden="true">
      {NODE_SYMBOLS[kind]}
    </svg>
  );
}

export function LineSymbol({ kind }: { kind: RelationKind }) {
  const style = LINE_STYLES[kind];
  return (
    <svg viewBox="0 0 24 8" className="h-2 w-5 shrink-0" aria-hidden="true">
      <line
        x1={1}
        y1={4}
        x2={23}
        y2={4}
        className={style.className}
        strokeWidth={style.width}
        strokeDasharray={style.dash}
      />
    </svg>
  );
}

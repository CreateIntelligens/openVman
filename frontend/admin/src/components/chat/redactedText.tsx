import { Children, Fragment, isValidElement, cloneElement } from "react";
import type { ReactNode, ReactElement } from "react";

const REDACTED_PATTERN = /\[REDACTED:([a-z0-9_]+)\]/gi;

const CATEGORY_LABELS: Record<string, string> = {
  phone: "電話",
  email: "信箱",
  name: "姓名",
  address: "地址",
  id: "身分證",
  credit_card: "信用卡",
  secret: "機密",
  url: "網址",
  ip: "IP",
  date_of_birth: "生日",
  passport: "護照",
  bank_account: "銀行帳號",
};

function labelFor(category: string): string {
  return CATEGORY_LABELS[category.toLowerCase()] ?? "個資";
}

export function RedactedPill({ category }: { category: string }) {
  const label = labelFor(category);
  return (
    <span
      title={`已遮蔽：${label}`}
      className="inline-flex items-center gap-1 rounded-md border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[0.8125rem] font-medium text-warn align-baseline"
    >
      <span className="material-symbols-outlined text-[0.875rem] leading-none">lock</span>
      {label}
    </span>
  );
}

export function renderWithRedactions(text: string): ReactNode[] {
  if (!text.includes("[REDACTED:")) {
    return [text];
  }
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  const matches = Array.from(text.matchAll(REDACTED_PATTERN));
  for (const match of matches) {
    const idx = match.index ?? 0;
    if (idx > lastIndex) {
      nodes.push(text.slice(lastIndex, idx));
    }
    nodes.push(<RedactedPill key={`r-${key++}`} category={match[1]} />);
    lastIndex = idx + match[0].length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

export function transformChildren(children: ReactNode): ReactNode {
  const out: ReactNode[] = [];
  let key = 0;
  Children.forEach(children, (child) => {
    if (typeof child === "string") {
      for (const node of renderWithRedactions(child)) {
        out.push(
          typeof node === "string"
            ? <Fragment key={`s-${key++}`}>{node}</Fragment>
            : node,
        );
      }
      return;
    }
    if (isValidElement(child)) {
      const element = child as ReactElement<{ children?: ReactNode }>;
      const inner = element.props?.children;
      if (inner !== undefined) {
        out.push(cloneElement(element, { key: element.key ?? `e-${key++}` }, transformChildren(inner)));
        return;
      }
    }
    out.push(child);
  });
  return out;
}

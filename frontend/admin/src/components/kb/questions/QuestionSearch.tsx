import { useState } from "react";

import type { QaQuestionRow } from "../../../api/knowledge";
import { languageKey, languageLabel } from "./allQuestions";

interface Props {
  value: string;
  rows: QaQuestionRow[];
  onChange: (value: string) => void;
  onOpen: (row: QaQuestionRow) => void;
}

export default function QuestionSearch({ value, rows, onChange, onOpen }: Props) {
  const [showResults, setShowResults] = useState(false);
  const term = value.trim().toLowerCase();
  const matching = term ? rows.filter((row) => `${row.question}\n${row.answer}`.toLowerCase().includes(term)) : [];
  return (
    <div className="relative border-b border-border bg-surface-raised px-4 py-3"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setShowResults(false);
      }}>
      <input id="knowledge-question-search" type="search" className="input w-full" placeholder="搜尋問題或答案"
        aria-label="搜尋問題或答案" value={value} onFocus={() => setShowResults(true)}
        onChange={(event) => { onChange(event.target.value); setShowResults(true); }}
        onKeyDown={(event) => {
          if (event.key === "Escape" && value) {
            event.stopPropagation();
            onChange("");
          }
          if (event.key === "Enter" && matching.length === 1 && !event.nativeEvent.isComposing) {
            onOpen(matching[0]);
          }
        }} />
      {showResults && term && (
        <div className="absolute inset-x-4 top-full z-20 max-h-[40dvh] overflow-y-auto rounded-b-lg border border-border bg-surface-raised shadow-lg">
          {matching.length > 0 ? (
            <ul aria-label="題目搜尋結果" className="divide-y divide-border">
              {matching.slice(0, 20).map((row) => (
                <li key={row.id}>
                  <button type="button" onClick={() => onOpen(row)}
                    className="grid w-full gap-1 px-3 py-2 text-left text-sm hover:bg-surface-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary">
                    <span className="break-words font-medium">{row.question}</span>
                    <span className="line-clamp-2 break-words text-content-muted">{row.answer}</span>
                    <span className="text-xs text-content-muted">{languageLabel(languageKey(row))}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <p role="status" className="px-3 py-2 text-sm text-content-muted">沒有符合的題目。</p>}
          {matching.length > 20 && <p className="px-3 py-2 text-sm text-content-muted">顯示前 20 題，請多輸入幾個字縮小範圍。</p>}
        </div>
      )}
    </div>
  );
}

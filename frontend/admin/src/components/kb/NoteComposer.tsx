import { useEffect, useId, useState } from "react";

import type { KnowledgeNoteFormat } from "../../api";
import { useUnsavedChanges } from "../../context/NavigationGuardContext";
import SegmentedControl from "../SegmentedControl";
import QaDocEditor from "./QaDocEditor";

const FORMAT_OPTIONS: { id: KnowledgeNoteFormat; label: string }[] = [
  { id: "text", label: "純文字" },
  { id: "qa", label: "問答" },
];

const FORMAT_COPY: Record<KnowledgeNoteFormat, { heading: string; hint: string; createLabel: string }> = {
  text: {
    heading: "自己輸入文件",
    hint: "建立後會放在「文件」的 notes 資料夾，AI 回答時會參考。",
    createLabel: "建立文件",
  },
  qa: {
    heading: "自己輸入問答",
    hint: "一題一列。建立後會放進快速問答，分類名稱就是上面的標題。",
    createLabel: "建立問答",
  },
};

export default function NoteComposer({
  creating,
  onClose,
  onCreate,
  initialFormat = "text",
}: {
  creating: boolean;
  onClose: () => void;
  onCreate: (title: string, content: string, format: KnowledgeNoteFormat) => void;
  /** 一打開就用哪種格式；已開著時換值也會跟著切，兩種格式已輸入的內容都留著。 */
  initialFormat?: KnowledgeNoteFormat;
}) {
  const [format, setFormat] = useState<KnowledgeNoteFormat>(initialFormat);
  const [title, setTitle] = useState("");
  const [textContent, setTextContent] = useState("");
  const [qaContent, setQaContent] = useState("");
  const titleInputId = useId();

  useEffect(() => {
    setFormat(initialFormat);
  }, [initialFormat]);

  const copy = FORMAT_COPY[format];
  const content = format === "qa" ? qaContent : textContent;
  const canCreate = !creating && title.trim().length > 0 && content.trim().length > 0;
  // 真的打了字才算未存：打開看一眼就走，不該被問要不要捨棄。
  const dirty = [title, textContent, qaContent].some((value) => value.trim() !== "");
  useUnsavedChanges("knowledge-note-composer", dirty, "正在輸入的內容");

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border bg-surface-raised px-4 py-2 dark:bg-surface/30">
        <div className="flex min-w-0 items-center gap-2">
          <button type="button" onClick={onClose} className="btn btn-ghost px-2.5">
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">arrow_back</span>
            返回
          </button>
          <h2 className="truncate text-base font-semibold text-content">{copy.heading}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl
            label="內容格式"
            options={FORMAT_OPTIONS}
            value={format}
            onChange={setFormat}
          />
          <button
            type="button"
            onClick={() => onCreate(title, content, format)}
            disabled={!canCreate}
            className="btn btn-primary"
          >
            <span aria-hidden="true" className={`material-symbols-outlined text-[1rem] ${creating ? "animate-spin" : ""}`}>
              {creating ? "sync" : "save"}
            </span>
            {creating ? "建立中…" : copy.createLabel}
          </button>
        </div>
      </div>

      <div className="shrink-0 space-y-2 px-4 pt-3">
        <div className="flex items-center gap-3">
          <label htmlFor={titleInputId} className="shrink-0 text-sm font-medium text-content-muted">標題</label>
          <input
            id={titleInputId}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="例如：產品定位整理"
            className="input min-w-0 flex-1 placeholder:text-content-subtle"
          />
        </div>
        <p className="text-xs text-content-muted">{copy.hint}</p>
      </div>

      {format === "qa" ? (
        <QaDocEditor content={qaContent} onChange={setQaContent} />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col px-4 pb-3 pt-2">
          <textarea
            aria-label="文件內容"
            value={textContent}
            onChange={(e) => setTextContent(e.target.value)}
            placeholder="在這裡貼上或輸入內容"
            className="input min-h-0 flex-1 resize-none placeholder:text-content-subtle"
          />
          <p className="mt-2 shrink-0 text-xs text-content-muted">{textContent.length.toLocaleString()} 字</p>
        </div>
      )}
    </div>
  );
}

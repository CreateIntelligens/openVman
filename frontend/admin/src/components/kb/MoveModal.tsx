import { useState } from "react";
import type { KnowledgeDocumentSummary } from "../../api";
import {
  displayDocumentPath,
  DOCUMENTS_ROOT_PATH,
  DOCUMENTS_SECTION_LABEL,
  fileNameOf,
  parentDirOf,
} from "./helpers";
import { useModalDismiss } from "./useModalDismiss";

const LISTED_SOURCE_LIMIT = 3;

/** knowledge 是內部的最上層，畫面上和樹一樣叫「文件」。 */
function folderPathLabel(dir: string): string {
  const relative = displayDocumentPath(dir);
  return relative
    ? [DOCUMENTS_SECTION_LABEL, ...relative.split("/")].join(" › ")
    : DOCUMENTS_SECTION_LABEL;
}

export default function MoveModal({
  sourcePaths,
  allDocuments,
  serverDirs,
  onMove,
  onClose,
}: {
  sourcePaths: string[];
  allDocuments: KnowledgeDocumentSummary[];
  serverDirs: string[];
  onMove: (targetDir: string) => void;
  onClose: () => void;
}) {
  const [selectedDir, setSelectedDir] = useState(() => parentDirOf(sourcePaths[0] ?? ""));

  const dirs = new Set<string>();
  dirs.add(DOCUMENTS_ROOT_PATH);
  for (const doc of allDocuments) {
    const parts = doc.path.split("/");
    for (let i = 1; i < parts.length; i++) {
      dirs.add(parts.slice(0, i).join("/"));
    }
  }
  for (const d of serverDirs) {
    dirs.add(d);
    const parts = d.split("/");
    for (let i = 1; i < parts.length; i++) {
      dirs.add(parts.slice(0, i).join("/"));
    }
  }
  const sortedDirs = [...dirs].sort();
  const isBatch = sourcePaths.length > 1;
  const sourceDir = isBatch ? null : parentDirOf(sourcePaths[0] ?? "");
  const filename = isBatch ? "" : fileNameOf(sourcePaths[0] ?? "");
  const allInSelectedDir = sourcePaths.every((path) => parentDirOf(path) === selectedDir);
  const listedNames = sourcePaths.slice(0, LISTED_SOURCE_LIMIT).map(fileNameOf).join("、");
  const unlistedCount = sourcePaths.length - LISTED_SOURCE_LIMIT;
  const dismiss = useModalDismiss(onClose);
  const title = isBatch ? `移動 ${sourcePaths.length} 個文件` : "移動文件";
  const targetLabel = folderPathLabel(selectedDir);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      {...dismiss}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="bg-surface-raised border border-border rounded-2xl shadow-2xl w-full max-w-md max-h-[70vh] flex flex-col mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-2 min-w-0">
            <span aria-hidden="true" className="material-symbols-outlined text-primary text-[1.25rem]">drive_file_move</span>
            <span className="text-sm font-semibold text-content ">{title}</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="關閉"
            className="p-1.5 rounded-lg text-content-muted hover:text-content hover:bg-surface-sunken transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="px-5 py-3 border-b border-border ">
          <p className="text-xs text-content-subtle mb-1">檔案</p>
          <p className="text-sm text-content font-mono truncate">
            {isBatch
              ? `${listedNames}${unlistedCount > 0 ? `，另有 ${unlistedCount} 個` : ""}`
              : filename}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          <p className="px-5 py-1 text-xs text-content-subtle font-semibold">要移到哪個資料夾</p>
          {sortedDirs.map((dir) => {
            const depth = dir.split("/").length - 1;
            const isCurrentDir = dir === sourceDir;
            const isSelected = dir === selectedDir;
            const label = dir === DOCUMENTS_ROOT_PATH
              ? `${DOCUMENTS_SECTION_LABEL}（最上層）`
              : fileNameOf(dir);
            return (
              <button
                key={dir}
                type="button"
                onClick={() => setSelectedDir(dir)}
                aria-pressed={isSelected}
                className={`w-full text-left px-5 py-2.5 flex items-center gap-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary ${
                  isSelected ? "bg-primary/10 text-primary" : "text-content-muted hover:bg-surface-sunken "
                }`}
                style={{ paddingLeft: `${1.25 + depth * 1}rem` }}
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[1.125rem]">{isSelected ? "folder_open" : "folder"}</span>
                <span className="text-sm truncate">{label}</span>
                {isCurrentDir && <span className="text-xs text-content-subtle ml-auto shrink-0">目前位置</span>}
              </button>
            );
          })}
        </div>
        <div className="px-5 py-4 border-t border-border flex items-center justify-between gap-3">
          <p title={targetLabel} className="text-xs text-content-muted truncate min-w-0">移到「{targetLabel}」</p>
          <div className="flex gap-2 shrink-0">
            <button type="button" onClick={onClose} className="btn btn-ghost">
              取消
            </button>
            <button
              type="button"
              onClick={() => onMove(selectedDir)}
              disabled={allInSelectedDir}
              className="btn btn-primary"
            >
              移動
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

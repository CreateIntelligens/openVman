import { useState } from "react";
import type { KnowledgeDocumentSummary } from "../../api";
import { useModalDismiss } from "./useModalDismiss";

export default function MoveModal({
  sourcePath,
  allDocuments,
  serverDirs,
  onMove,
  onClose,
}: {
  sourcePath: string;
  allDocuments: KnowledgeDocumentSummary[];
  serverDirs: string[];
  onMove: (source: string, targetDir: string) => void;
  onClose: () => void;
}) {
  const [selectedDir, setSelectedDir] = useState(() => {
    const parts = sourcePath.split("/");
    return parts.slice(0, -1).join("/") || "";
  });

  const dirs = new Set<string>();
  dirs.add("knowledge");
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
  const sourceDir = sourcePath.split("/").slice(0, -1).join("/");
  const filename = sourcePath.split("/").pop() || "";
  const dismiss = useModalDismiss(onClose);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      {...dismiss}
    >
      <div className="bg-surface-raised border border-border rounded-2xl shadow-2xl w-full max-w-md max-h-[70vh] flex flex-col mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-2 min-w-0">
            <span className="material-symbols-outlined text-primary text-[1.25rem]">drive_file_move</span>
            <span className="text-sm font-semibold text-content ">移動文件</span>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-content-muted hover:text-content hover:bg-surface-sunken transition-colors">
            <span className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>
        <div className="px-5 py-3 border-b border-border ">
          <p className="text-xs text-content-subtle mb-1">檔案</p>
          <p className="text-sm text-content font-mono truncate">{filename}</p>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          <p className="px-5 py-1 text-xs text-content-subtle font-semibold uppercase tracking-wider">選擇目標資料夾</p>
          {sortedDirs.map((dir) => {
            const depth = dir.split("/").length - 1;
            const isCurrentDir = dir === sourceDir;
            const isSelected = dir === selectedDir;
            const label = dir.split("/").pop() || dir;
            return (
              <button
                key={dir}
                onClick={() => setSelectedDir(dir)}
                className={`w-full text-left px-5 py-2.5 flex items-center gap-2 transition-colors ${
                  isSelected ? "bg-primary/10 text-primary" : "text-content-muted hover:bg-surface-sunken "
                }`}
                style={{ paddingLeft: `${1.25 + depth * 1}rem` }}
              >
                <span className="material-symbols-outlined text-[1.125rem]">{isSelected ? "folder_open" : "folder"}</span>
                <span className="text-sm truncate">{label}</span>
                {isCurrentDir && <span className="text-[0.625rem] text-content-subtle ml-auto shrink-0">目前位置</span>}
              </button>
            );
          })}
        </div>
        <div className="px-5 py-4 border-t border-border flex items-center justify-between gap-3">
          <p className="text-xs text-content-subtle truncate min-w-0">→ {selectedDir}/{filename}</p>
          <div className="flex gap-2 shrink-0">
            <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-sm text-content-muted hover:text-content hover:bg-surface-sunken transition-colors">
              取消
            </button>
            <button
              onClick={() => onMove(sourcePath, selectedDir)}
              disabled={selectedDir === sourceDir}
              className="px-4 py-1.5 rounded-lg bg-primary text-sm font-bold text-white hover:bg-primary/90 transition-all disabled:opacity-30"
            >
              移動
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

import React, { useState, useEffect } from "react";
import MarkdownPreview from "../MarkdownPreview";

interface FileEditorProps {
  content: string;
  path: string;
  onSave: (path: string, content: string) => Promise<void>;
  saving?: boolean;
}

const FileEditor: React.FC<FileEditorProps> = ({
  content,
  path,
  onSave,
  saving = false,
}) => {
  const [draftContent, setDraftContent] = useState(content);
  const [mode, setMode] = useState<"edit" | "split" | "preview">("split");

  useEffect(() => {
    setDraftContent(content);
  }, [content]);

  const hasUnsavedChanges = draftContent !== content;

  return (
    <div className="flex flex-col h-full bg-slate-950/20 rounded-xl border border-slate-800/60 overflow-hidden shadow-2xl">
      {/* Editor Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800/60 bg-slate-900/40">
        <div className="flex items-center gap-3 min-w-0">
          <span className="material-symbols-outlined text-primary text-[20px]">edit_document</span>
          <span className="text-sm font-mono text-slate-300 truncate">{path || "New File"}</span>
          {hasUnsavedChanges && (
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse shrink-0" title="Unsaved changes" />
          )}
        </div>

        <div className="flex items-center gap-3">
          <div className="flex bg-slate-800/50 rounded-lg p-1 border border-slate-700/50">
            {(["edit", "split", "preview"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-3 py-1 text-[11px] font-bold uppercase tracking-wider rounded-md transition-all ${
                  mode === m
                    ? "bg-primary text-white shadow-lg shadow-primary/20"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          <button
            onClick={() => onSave(path, draftContent)}
            disabled={saving || !hasUnsavedChanges}
            className="flex items-center gap-2 px-4 py-1.5 rounded-lg bg-primary text-white text-xs font-bold hover:bg-primary/90 transition-all disabled:opacity-50 disabled:grayscale shadow-lg shadow-primary/10"
          >
            <span className={`material-symbols-outlined text-[16px] ${saving ? "animate-spin" : ""}`}>
              {saving ? "sync" : "save"}
            </span>
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

      {/* Editor Body */}
      <div className="flex-1 flex overflow-hidden min-h-0 bg-slate-950/40">
        {(mode === "edit" || mode === "split") && (
          <div className={`flex-1 flex flex-col min-h-0 ${mode === "split" ? "border-r border-slate-800/60" : ""}`}>
            <textarea
              value={draftContent}
              onChange={(e) => setDraftContent(e.target.value)}
              className="flex-1 w-full bg-transparent p-6 text-sm leading-relaxed text-slate-200 font-mono resize-none focus:outline-none scrollbar-thin overflow-y-auto"
              spellCheck={false}
              placeholder="# Start writing..."
            />
          </div>
        )}

        {(mode === "preview" || mode === "split") && (
          <div className="flex-1 overflow-y-auto p-6 bg-slate-900/10 scrollbar-thin">
            <div className="max-w-none prose-invert">
              <MarkdownPreview content={draftContent} />
            </div>
          </div>
        )}
      </div>

      {/* Editor Footer */}
      <div className="px-4 py-2 border-t border-slate-800/60 bg-slate-900/40 flex items-center justify-between text-[10px] text-slate-500 font-medium uppercase tracking-widest">
        <span>{draftContent.length} characters</span>
        <div className="flex items-center gap-4">
          <span>Markdown Enabled</span>
          <span className="text-primary/60">UTF-8</span>
        </div>
      </div>
    </div>
  );
};

export default FileEditor;

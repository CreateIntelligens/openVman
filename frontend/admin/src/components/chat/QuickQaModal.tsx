import { useState, useEffect, useMemo } from "react";
import { useQaNodes, type QaNode } from "../../hooks/useQaNodes";

import { buildQuickQaQuestionText } from "./quickQaQuestion";

interface QuickQaModalProps {
  open: boolean;
  onClose: () => void;
  onSelectQuestion: (question: string) => void;
}

export default function QuickQaModal({ open, onClose, onSelectQuestion }: QuickQaModalProps) {
  const { nodesTree, loading, error, fetchTree } = useQaNodes();
  const [currentPath, setCurrentPath] = useState<QaNode[]>([]);

  useEffect(() => {
    if (open) {
      setCurrentPath([]);
      void fetchTree();
    }
  }, [open, fetchTree]);

  const currentNode = useMemo(() => {
    if (currentPath.length === 0) return null;
    return currentPath[currentPath.length - 1];
  }, [currentPath]);

  const currentSubNodes = useMemo(() => {
    if (!currentNode) return nodesTree;
    return currentNode.children ?? [];
  }, [currentNode, nodesTree]);

  const currentQuestions = useMemo(() => {
    if (!currentNode) return [];
    return (currentNode.qa_entries ?? []).filter((e) => !e.hidden);
  }, [currentNode]);

  const currentTitle = useMemo(() => {
    if (!currentNode) return "快速問答分類";
    return currentNode.label || currentNode.node_id;
  }, [currentNode]);

  if (!open) return null;

  const handleEnterNode = (node: QaNode) => {
    setCurrentPath((prev) => [...prev, node]);
  };

  const handleGoBack = () => {
    setCurrentPath((prev) => prev.slice(0, -1));
  };

  const handleSelect = (rawQuestion: string) => {
    const { sendText } = buildQuickQaQuestionText(
      rawQuestion,
      currentNode?.label || "",
    );

    onSelectQuestion(sendText);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs">
      <div className="flex h-[80vh] w-full max-w-2xl flex-col rounded-2xl border border-border bg-surface-raised shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-5">
          <div className="flex items-center gap-3">
            {currentPath.length > 0 ? (
              <button
                type="button"
                onClick={handleGoBack}
                className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
              >
                <span className="material-symbols-outlined text-[1rem]">arrow_back</span>
                返回上一層
              </button>
            ) : (
              <span className="material-symbols-outlined text-primary text-[1.25rem]">help_center</span>
            )}
            <h3 className="text-base font-semibold text-content">{currentTitle}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-muted hover:bg-surface-sunken hover:text-content"
          >
            <span className="material-symbols-outlined text-[1.25rem]">close</span>
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading && (
            <div className="flex h-48 items-center justify-center text-sm text-content-muted">
              <span className="material-symbols-outlined animate-spin text-[1.5rem] mr-2">progress_activity</span>
              正在載入問答分類...
            </div>
          )}

          {error && (
            <div className="flex h-48 flex-col items-center justify-center text-center text-sm text-danger">
              <p className="mb-3">{error}</p>
              <button
                type="button"
                onClick={() => void fetchTree()}
                className="rounded-lg bg-primary px-4 py-1.5 text-xs font-medium text-content-inverse hover:opacity-90"
              >
                重新整理
              </button>
            </div>
          )}

          {!loading && !error && currentSubNodes.length === 0 && currentQuestions.length === 0 && (
            <div className="flex h-48 items-center justify-center text-sm text-content-muted">
              此分類尚無問答內容
            </div>
          )}

          {!loading && !error && (
            <div className="grid gap-3 sm:grid-cols-2">
              {/* Folder Nodes */}
              {currentSubNodes.map((node) => (
                <button
                  key={node.node_id}
                  type="button"
                  onClick={() => handleEnterNode(node)}
                  className="flex items-center justify-between rounded-xl border border-border bg-surface p-4 text-left font-medium text-content transition-all hover:border-primary/50 hover:bg-primary/5 hover:shadow-xs"
                >
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-primary text-[1.25rem]">folder</span>
                    <span className="truncate text-sm">{node.label || node.node_id}</span>
                  </div>
                  <span className="material-symbols-outlined text-content-subtle text-[1rem]">chevron_right</span>
                </button>
              ))}

              {/* Question items */}
              {currentQuestions.map((qa, idx) => {
                const { displayText } = buildQuickQaQuestionText(
                  qa.question,
                  currentNode?.label || "",
                );
                return (
                  <button
                    key={`${qa.question}-${idx}`}
                    type="button"
                    onClick={() => handleSelect(qa.question)}
                    className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 text-left font-normal text-content transition-all hover:border-primary/50 hover:bg-primary/5 hover:shadow-xs"
                  >
                    <span className="material-symbols-outlined text-content-subtle text-[1.125rem]">help</span>
                    <span className="text-sm leading-relaxed">{displayText}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

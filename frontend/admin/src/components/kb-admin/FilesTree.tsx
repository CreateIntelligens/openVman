import React, { useState } from "react";
import { KBNode } from "./types";

interface FilesTreeProps {
  nodes: KBNode[];
  selectedId: string | null;
  onSelect: (node: KBNode) => void;
  onToggleFolder?: (nodeId: string, expanded: boolean) => void;
}

const FilesTree: React.FC<FilesTreeProps> = ({
  nodes,
  selectedId,
  onSelect,
  onToggleFolder,
}) => {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  const toggleExpand = (id: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      const isExpanded = next.has(id);
      if (isExpanded) {
        next.delete(id);
      } else {
        next.add(id);
      }
      onToggleFolder?.(id, !isExpanded);
      return next;
    });
  };

  const renderNode = (node: KBNode, depth: number = 0) => {
    const isExpanded = expandedNodes.has(node.id);
    const isSelected = selectedId === node.id;
    const hasChildren = node.children && node.children.length > 0;

    return (
      <div key={node.id} className="select-none">
        <div
          className={`group flex items-center py-1.5 px-2 rounded-lg cursor-pointer transition-all duration-200 ${
            isSelected
              ? "bg-primary/20 text-primary"
              : "hover:bg-slate-800/60 text-slate-300 hover:text-white"
          }`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => {
            if (node.type === "folder") {
              toggleExpand(node.id);
            }
            onSelect(node);
          }}
        >
          <div className="w-5 h-5 flex items-center justify-center shrink-0">
            {node.type === "folder" ? (
              <span className="material-symbols-outlined text-[18px] text-amber-500/80">
                {isExpanded ? "folder_open" : "folder"}
              </span>
            ) : (
              <span className={`material-symbols-outlined text-[18px] ${
                node.id.endsWith(".md") ? "text-sky-400" : "text-slate-400"
              }`}>
                {node.id.endsWith(".md") ? "markdown" : "description"}
              </span>
            )}
          </div>
          
          <span className={`ml-2 text-sm truncate flex-1 ${isSelected ? "font-bold" : ""}`}>
            {node.name}
          </span>

          {node.type === "file" && (
            <div className="flex items-center gap-1.5 shrink-0 ml-2">
              {node.status === "syncing" && (
                <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" title="Syncing..." />
              )}
              {node.status === "error" && (
                <span className="material-symbols-outlined text-rose-500 text-[14px]" title="Error indexing">
                  error
                </span>
              )}
              {node.status === "indexed" && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/60" title="Indexed" />
              )}
            </div>
          )}
        </div>

        {node.type === "folder" && isExpanded && node.children && (
          <div className="transition-all duration-300">
            {node.children.map((child) => renderNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-slate-500">
        <span className="material-symbols-outlined text-3xl mb-2 opacity-20">folder_off</span>
        <p className="text-xs uppercase tracking-widest font-bold">No files found</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      {nodes.map((node) => renderNode(node))}
    </div>
  );
};

export default FilesTree;

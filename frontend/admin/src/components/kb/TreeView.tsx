import type { TreeNode } from "./helpers";
import StatusDot from "./StatusDot";

export default function TreeView({
  node,
  depth,
  selectedPath,
  expandedDirs,
  onSelect,
  onToggle,
  onDelete,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string;
  expandedDirs: Set<string>;
  onSelect: (node: TreeNode) => void;
  onToggle: (path: string) => void;
  onDelete: (node: TreeNode) => void;
}) {
  const isExpanded = expandedDirs.has(node.path);
  const isSelected = selectedPath === node.path;

  return (
    <div>
      <div
        className={`group flex items-center py-1 px-2 cursor-pointer transition-all duration-150 ${
          isSelected
            ? "bg-primary/15 text-primary"
            : "hover:bg-slate-800/50 text-slate-300 hover:text-white"
        }`}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
        onClick={() => onSelect(node)}
      >
        {/* Expand arrow for folders */}
        <div className="w-4 h-4 flex items-center justify-center shrink-0">
          {node.type === "folder" ? (
            <span
              className={`material-symbols-outlined text-[14px] text-slate-500 transition-transform duration-150 ${isExpanded ? "rotate-90" : ""}`}
              onClick={(e) => { e.stopPropagation(); onToggle(node.path); }}
            >
              chevron_right
            </span>
          ) : null}
        </div>

        {/* Icon */}
        <div className="w-5 h-5 flex items-center justify-center shrink-0 ml-0.5">
          {node.type === "folder" ? (
            <span className="material-symbols-outlined text-[16px] text-amber-500/80">
              {isExpanded ? "folder_open" : "folder"}
            </span>
          ) : (
            <span className={`material-symbols-outlined text-[16px] ${
              node.name.endsWith(".md") ? "text-sky-400" : "text-slate-400"
            }`}>
              {node.name.endsWith(".md") ? "markdown" : "description"}
            </span>
          )}
        </div>

        {/* Name */}
        <span className={`ml-1.5 text-xs truncate flex-1 ${isSelected ? "font-semibold" : ""}`}>
          {node.name}
        </span>

        {/* Status indicator for files */}
        {node.type === "file" && node.doc && (
          <div className="flex items-center gap-1 shrink-0 ml-1">
            <StatusDot doc={node.doc} />
          </div>
        )}

        {/* Delete on hover */}
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(node); }}
          className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-slate-600 hover:text-red-400 transition-opacity shrink-0 ml-1"
          title="刪除"
        >
          <span className="material-symbols-outlined text-[13px]">close</span>
        </button>
      </div>

      {/* Children */}
      {node.type === "folder" && isExpanded && node.children.length > 0 && (
        <div>
          {node.children.map((child) => (
            <TreeView
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              expandedDirs={expandedDirs}
              onSelect={onSelect}
              onToggle={onToggle}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}

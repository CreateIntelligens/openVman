import type { TreeNode } from "./helpers";
import StatusDot from "./StatusDot";

export default function TreeView({
  node,
  depth,
  selectedPath,
  expandedDirs,
  onSelect,
  onToggle,
  draggingPath,
  sourceDragDir,
  dropTargetPath,
  onDragStart,
  onDragEnd,
  onDragTargetChange,
  onDropFile,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string;
  expandedDirs: Set<string>;
  onSelect: (node: TreeNode) => void;
  onToggle: (path: string) => void;
  draggingPath: string | null;
  sourceDragDir: string;
  dropTargetPath: string | null;
  onDragStart: (node: TreeNode) => void;
  onDragEnd: () => void;
  onDragTargetChange: (path: string | null) => void;
  onDropFile: (targetDir: string) => void;
}) {
  const isExpanded = expandedDirs.has(node.path);
  const isSelected = selectedPath === node.path;
  const effectiveDropDir = node.type === "folder" ? node.path : node.path.split("/").slice(0, -1).join("/");
  const isDropTarget = dropTargetPath === effectiveDropDir && !!draggingPath && effectiveDropDir !== sourceDragDir;
  const canAcceptDrop = !!draggingPath && effectiveDropDir !== sourceDragDir && node.path !== draggingPath;

  return (
    <div>
      <div
        className={`group flex items-center py-1 px-2 cursor-pointer transition-all duration-150 ${
          isDropTarget
            ? "bg-primary/10 text-primary ring-1 ring-inset ring-primary/20"
            : isSelected
              ? "bg-primary/15 text-primary"
              : "hover:bg-slate-100 dark:hover:bg-slate-800/50 text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
        }`}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
        onClick={() => onSelect(node)}
        draggable={node.type === "file"}
        onDragStart={(event) => {
          if (node.type !== "file") return;
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", node.path);
          onDragStart(node);
        }}
        onDragEnd={onDragEnd}
        onDragOver={(event) => {
          if (!canAcceptDrop) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
          onDragTargetChange(effectiveDropDir);
        }}
        onDragEnter={(event) => {
          if (!canAcceptDrop) return;
          event.preventDefault();
          onDragTargetChange(effectiveDropDir);
        }}
        onDragLeave={() => {
          if (isDropTarget) onDragTargetChange(null);
        }}
        onDrop={(event) => {
          if (!canAcceptDrop) return;
          event.preventDefault();
          event.stopPropagation();
          onDropFile(effectiveDropDir);
        }}
      >
        {/* Expand arrow for folders */}
        <div className="w-4 h-4 flex items-center justify-center shrink-0">
          {node.type === "folder" ? (
            <span
              className={`material-symbols-outlined text-[1rem] text-slate-500 transition-transform duration-150 ${isExpanded ? "rotate-90" : ""}`}
              onClick={(e) => { e.stopPropagation(); onToggle(node.path); }}
            >
              chevron_right
            </span>
          ) : null}
        </div>

        {/* Icon */}
        <div className="w-5 h-5 flex items-center justify-center shrink-0 ml-0.5">
          {node.type === "folder" ? (
            <span className="material-symbols-outlined text-[1.125rem] text-amber-500/80">
              {isExpanded ? "folder_open" : "folder"}
            </span>
          ) : (
            <span className={`material-symbols-outlined text-[1.125rem] ${
              node.name.endsWith(".md") ? "text-sky-400" : "text-slate-400"
            }`}>
              {node.name.endsWith(".md") ? "markdown" : "description"}
            </span>
          )}
        </div>

        {/* Name */}
        <span className={`ml-1.5 text-sm truncate flex-1 ${isSelected ? "font-semibold" : ""}`}>
          {node.name}
        </span>

        {/* Status indicator for files */}
        {node.type === "file" && node.doc && (
          <div className="flex items-center gap-1 shrink-0 ml-1">
            <StatusDot doc={node.doc} />
          </div>
        )}

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
              draggingPath={draggingPath}
              sourceDragDir={sourceDragDir}
              dropTargetPath={dropTargetPath}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              onDragTargetChange={onDragTargetChange}
              onDropFile={onDropFile}
            />
          ))}
        </div>
      )}
    </div>
  );
}

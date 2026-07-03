import type { TreeNode } from "./helpers";
import { qaTreeNodePath } from "./helpers";
import StatusDot from "./StatusDot";

function TreeActionButton({
  title,
  icon,
  variant = "default",
  onClick,
}: {
  title: string;
  icon: string;
  variant?: "default" | "primary" | "danger";
  onClick: () => void;
}) {
  const variantClass = {
    default: "hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200",
    primary: "hover:bg-primary/10 hover:text-primary",
    danger: "hover:bg-danger/10 hover:text-danger",
  }[variant];

  return (
    <button
      type="button"
      title={title}
      className={`rounded-md p-1 text-slate-400 transition-colors ${variantClass}`}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    >
      <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">{icon}</span>
    </button>
  );
}

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
  onDeleteFolder,
  onSelectQaNode,
  onCreateQaNode,
  onRenameQaNode,
  onToggleQaNodeHidden,
  onDeleteQaNode,
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
  onDeleteFolder: (path: string) => void;
  onSelectQaNode?: (nodeId: string) => void;
  onCreateQaNode?: (parentNodeId: string | null) => void;
  onRenameQaNode?: (nodeId: string) => void;
  onToggleQaNodeHidden?: (nodeId: string, hidden: boolean) => void;
  onDeleteQaNode?: (nodeId: string) => void;
}) {
  const isExpanded = expandedDirs.has(node.path);
  const isSelected = selectedPath === node.path;
  const isQaRoot = node.treeKind === "qa-root";
  const isQaNode = node.treeKind === "qa-node";
  const isQaEntry = node.treeKind === "qa-entry";
  const qaNodeId = node.qaNodeId;
  const effectiveDropDir = node.type === "folder" ? node.path : node.path.split("/").slice(0, -1).join("/");
  let dropTargetKey: string;
  if (isQaRoot) {
    dropTargetKey = node.path;
  } else if (isQaNode || isQaEntry) {
    dropTargetKey = qaTreeNodePath(qaNodeId || "");
  } else {
    dropTargetKey = effectiveDropDir;
  }

  const canAcceptDrop =
    !!draggingPath &&
    node.path !== draggingPath &&
    (isQaRoot || isQaNode || isQaEntry || (!node.virtual && effectiveDropDir !== sourceDragDir));
  const isDropTarget = dropTargetPath === dropTargetKey && !!draggingPath;
  const canDeleteFolder = node.type === "folder" && node.path !== "knowledge" && !node.virtual;

  const handleSelect = () => {
    if (isQaRoot) {
      onToggle(node.path);
      return;
    }
    if ((isQaNode || isQaEntry) && qaNodeId && onSelectQaNode) {
      onSelectQaNode(qaNodeId);
      return;
    }
    onSelect(node);
  };

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
        onClick={handleSelect}
        draggable={node.type === "file" && !node.virtual}
        onDragStart={(event) => {
          if (node.type !== "file" || node.virtual) return;
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", node.path);
          onDragStart(node);
        }}
        onDragEnd={onDragEnd}
        onDragOver={(event) => {
          if (!canAcceptDrop) return;
          event.preventDefault();
          if (event.dataTransfer) {
            event.dataTransfer.dropEffect = "move";
          }
          onDragTargetChange(dropTargetKey);
        }}
        onDragEnter={(event) => {
          if (!canAcceptDrop) return;
          event.preventDefault();
          onDragTargetChange(dropTargetKey);
        }}
        onDragLeave={() => {
          if (isDropTarget) onDragTargetChange(null);
        }}
        onDrop={(event) => {
          if (!canAcceptDrop) return;
          event.preventDefault();
          event.stopPropagation();
          onDropFile(dropTargetKey);
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
          {isQaRoot ? (
            <span className="material-symbols-outlined text-[1.125rem] text-primary/80">
              quiz
            </span>
          ) : isQaEntry ? (
            <span className="material-symbols-outlined text-[1.05rem] text-amber-500/80">
              help
            </span>
          ) : node.type === "folder" ? (
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
        <span
          className={`ml-1.5 text-sm truncate flex-1 ${
            isSelected ? "font-semibold" : ""
          } ${node.qaHidden ? "opacity-40" : ""}`}
        >
          {node.name}
        </span>

        {/* Status indicator for files */}
        {node.type === "file" && node.doc && !node.virtual && (
          <div className="flex items-center gap-1 shrink-0 ml-1">
            <StatusDot doc={node.doc} />
          </div>
        )}

        {isQaRoot && onCreateQaNode && (
          <button
            type="button"
            title="新增快速問答節點"
            className="ml-1 shrink-0 rounded-md p-1 text-slate-400 opacity-0 transition-colors hover:bg-primary/10 hover:text-primary focus:opacity-100 group-hover:opacity-100"
            onClick={(event) => {
              event.stopPropagation();
              onCreateQaNode(null);
            }}
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">add</span>
          </button>
        )}

        {isQaNode && qaNodeId && (
          <div className="ml-1 flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            {onToggleQaNodeHidden && (
              <TreeActionButton
                title={node.qaHidden ? "顯示節點" : "隱藏節點"}
                icon={node.qaHidden ? "visibility_off" : "visibility"}
                onClick={() => onToggleQaNodeHidden(qaNodeId, !node.qaHidden)}
              />
            )}
            {onCreateQaNode && (
              <TreeActionButton
                title="新增子節點"
                icon="add"
                variant="primary"
                onClick={() => onCreateQaNode(qaNodeId)}
              />
            )}
            {onRenameQaNode && (
              <TreeActionButton
                title="修改名稱"
                icon="edit"
                onClick={() => onRenameQaNode(qaNodeId)}
              />
            )}
            {onDeleteQaNode && (
              <TreeActionButton
                title="刪除節點"
                icon="delete"
                variant="danger"
                onClick={() => onDeleteQaNode(qaNodeId)}
              />
            )}
          </div>
        )}

        {canDeleteFolder && (
          <button
            type="button"
            aria-label={`刪除資料夾 ${node.path}`}
            className="ml-1 shrink-0 rounded-md p-1 text-slate-400 opacity-0 transition-colors hover:bg-red-500/10 hover:text-red-400 focus:opacity-100 group-hover:opacity-100"
            onClick={(event) => {
              event.stopPropagation();
              onDeleteFolder(node.path);
            }}
          >
            <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">delete</span>
          </button>
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
              onDeleteFolder={onDeleteFolder}
              onSelectQaNode={onSelectQaNode}
              onCreateQaNode={onCreateQaNode}
              onRenameQaNode={onRenameQaNode}
              onToggleQaNodeHidden={onToggleQaNodeHidden}
              onDeleteQaNode={onDeleteQaNode}
            />
          ))}
        </div>
      )}
    </div>
  );
}

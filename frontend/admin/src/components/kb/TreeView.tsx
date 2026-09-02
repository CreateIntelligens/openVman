import { useId } from "react";
import type { KeyboardEvent, MouseEvent } from "react";

import type { TreeNode } from "./helpers";
import {
  parseQaEntryDragPath,
  parseQaNodeDragPath,
  qaEntryDragPath,
  qaNodeDragPath,
  qaTreeNodePath,
} from "./helpers";
import StatusDot from "./StatusDot";

// QA 節點的操作按鈕以覆蓋方式掛在列尾：absolute 不佔文流，名稱才有完整寬度；
// 用 opacity 而非 display 隱藏，鍵盤 Tab 仍能聚焦並讓按鈕群顯示。
const QA_ACTIONS_OVERLAY_CLASS =
  "absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-0.5 rounded-md bg-inherit pl-1 opacity-0 pointer-events-none transition-opacity focus-within:opacity-100 focus-within:pointer-events-auto group-hover:opacity-100 group-hover:pointer-events-auto";

function TreeActionButton({
  title,
  icon,
  variant = "default",
  onClick,
}: {
  title: string;
  icon: string;
  variant?: "default" | "primary" | "danger";
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const variantClass = {
    default: "hover:bg-surface-sunken hover:text-content ",
    primary: "hover:bg-primary/10 hover:text-primary",
    danger: "hover:bg-danger/10 hover:text-danger",
  }[variant];

  return (
    <button
      type="button"
      aria-label={title}
      title={title}
      className={`rounded-md p-1 text-content-subtle transition-colors ${variantClass}`}
      onClick={(event) => {
        event.stopPropagation();
        onClick(event);
      }}
    >
      <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">{icon}</span>
    </button>
  );
}

function hasVisibleSelectedNode(
  node: TreeNode,
  selectedPath: string,
  expandedDirs: Set<string>,
): boolean {
  if (node.path === selectedPath) {
    return true;
  }
  if (node.type !== "folder" || !expandedDirs.has(node.path)) {
    return false;
  }
  return node.children.some((child) =>
    hasVisibleSelectedNode(child, selectedPath, expandedDirs),
  );
}

function getVisibleTreeItems(treeItem: HTMLElement): HTMLElement[] {
  const tree = treeItem.closest('[role="tree"]');
  if (!tree) {
    return [];
  }
  return Array.from(tree.querySelectorAll<HTMLElement>('[role="treeitem"]'));
}

function focusTreeItem(treeItem: HTMLElement | undefined): void {
  if (!treeItem) {
    return;
  }
  const visibleItems = getVisibleTreeItems(treeItem);
  visibleItems.forEach((item) => {
    item.tabIndex = item === treeItem ? 0 : -1;
  });
  treeItem.focus();
}

function isKeyboardMoveActive(treeItem: HTMLElement): boolean {
  return treeItem.closest<HTMLElement>('[role="tree"]')?.dataset.keyboardMove === "true";
}

function finishKeyboardMove(treeItem: HTMLElement): void {
  const tree = treeItem.closest<HTMLElement>('[role="tree"]');
  if (tree) {
    delete tree.dataset.keyboardMove;
  }
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
  onOrderQaNode,
  canDropQaNode,
  canDropQaEntry,
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
  onOrderQaNode?: (parentNodeId: string | null) => void;
  canDropQaNode?: (draggedPath: string, targetPath: string) => boolean;
  canDropQaEntry?: (draggedPath: string, targetPath: string) => boolean;
}) {
  const instructionsId = useId();
  const isExpanded = expandedDirs.has(node.path);
  const isSelected = selectedPath === node.path;
  const isQaRoot = node.treeKind === "qa-root";
  const isQaNode = node.treeKind === "qa-node";
  const isQaEntry = node.treeKind === "qa-entry";
  const qaNodeId = node.qaNodeId;
  const draggingQaNodeId = draggingPath ? parseQaNodeDragPath(draggingPath) : null;
  const draggingQaEntry = draggingPath ? parseQaEntryDragPath(draggingPath) : null;
  const qaNodeDropTargetKey = qaNodeId ? qaTreeNodePath(qaNodeId) : node.path;
  const qaNodeReorderTargetKey = qaNodeId ? qaNodeDragPath(qaNodeId) : node.path;
  const qaEntryReorderTargetKey = qaNodeId
    ? qaEntryDragPath(qaNodeId, node.qaEntryQuestion ?? node.name)
    : node.path;
  const nodeDragPath = isQaNode && qaNodeId
    ? qaNodeDragPath(qaNodeId)
    : isQaEntry && qaNodeId
      ? qaEntryDragPath(qaNodeId, node.qaEntryQuestion ?? node.name)
      : node.path;
  const isDraggable = (node.type === "file" && !node.virtual) || isQaNode || isQaEntry;
  const isDraggingThisNode = draggingPath === nodeDragPath;
  const effectiveDropDir = node.type === "folder" ? node.path : node.path.split("/").slice(0, -1).join("/");
  let dropTargetKey: string;
  if (isQaRoot) {
    dropTargetKey = node.path;
  } else if (isQaNode) {
    dropTargetKey = draggingQaNodeId ? qaNodeReorderTargetKey : qaNodeDropTargetKey;
  } else if (isQaEntry) {
    dropTargetKey = draggingQaEntry ? qaEntryReorderTargetKey : qaNodeDropTargetKey;
  } else {
    dropTargetKey = effectiveDropDir;
  }

  const canAcceptDrop =
    !!draggingPath &&
    node.path !== draggingPath &&
    (draggingQaNodeId
      ? (isQaRoot || (isQaNode && !!canDropQaNode && canDropQaNode(draggingPath, dropTargetKey)))
      : draggingQaEntry
        ? (isQaEntry && !!canDropQaEntry && canDropQaEntry(draggingPath, dropTargetKey))
      : (isQaRoot || isQaNode || isQaEntry || (!node.virtual && effectiveDropDir !== sourceDragDir)));
  const isDropTarget = dropTargetPath === dropTargetKey && !!draggingPath;
  const canDeleteFolder = node.type === "folder" && node.path !== "knowledge" && !node.virtual;
  const isTreeTabStop = isSelected ||
    (depth === 0 && !hasVisibleSelectedNode(node, selectedPath, expandedDirs));

  const handleSelect = (treeItem: HTMLElement) => {
    if (draggingPath && isKeyboardMoveActive(treeItem)) {
      if (isDraggingThisNode) {
        finishKeyboardMove(treeItem);
        onDragEnd();
      } else if (canAcceptDrop) {
        finishKeyboardMove(treeItem);
        onDragTargetChange(dropTargetKey);
        onDropFile(dropTargetKey);
      }
      return;
    }
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

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) {
      return;
    }

    const currentItem = event.currentTarget;
    const visibleItems = getVisibleTreeItems(currentItem);
    const currentIndex = visibleItems.indexOf(currentItem);
    const focusAt = (index: number) => {
      focusTreeItem(visibleItems[index]);
    };

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusAt(Math.min(currentIndex + 1, visibleItems.length - 1));
        break;
      case "ArrowUp":
        event.preventDefault();
        focusAt(Math.max(currentIndex - 1, 0));
        break;
      case "Home":
        event.preventDefault();
        focusAt(0);
        break;
      case "End":
        event.preventDefault();
        focusAt(visibleItems.length - 1);
        break;
      case "ArrowRight": {
        if (node.type !== "folder") {
          return;
        }
        event.preventDefault();
        if (!isExpanded) {
          onToggle(node.path);
          return;
        }
        const childGroup = currentItem.nextElementSibling;
        const firstChild = childGroup?.getAttribute("role") === "group"
          ? childGroup.querySelector<HTMLElement>('[role="treeitem"]')
          : null;
        focusTreeItem(firstChild ?? undefined);
        break;
      }
      case "ArrowLeft": {
        event.preventDefault();
        if (node.type === "folder" && isExpanded) {
          onToggle(node.path);
          return;
        }
        const parentGroup = currentItem.parentElement?.parentElement;
        const parentItem = parentGroup?.getAttribute("role") === "group"
          ? parentGroup.previousElementSibling
          : null;
        focusTreeItem(parentItem instanceof HTMLElement ? parentItem : undefined);
        break;
      }
      case "Enter":
      case " ":
        event.preventDefault();
        handleSelect(currentItem);
        break;
      case "Escape":
        if (draggingPath && isKeyboardMoveActive(currentItem)) {
          event.preventDefault();
          finishKeyboardMove(currentItem);
          onDragEnd();
        }
        break;
      default:
        break;
    }
  };

  return (
    <div
      role={depth === 0 ? "tree" : "none"}
      aria-label={depth === 0 ? "知識庫目錄" : undefined}
      aria-describedby={depth === 0 ? instructionsId : undefined}
    >
      {depth === 0 && (
        <span id={instructionsId} className="sr-only">
          使用方向鍵巡覽，Enter 或空白鍵開啟。選擇「使用鍵盤移動」後，移至目標並按 Enter 或空白鍵放置，Escape 取消。
        </span>
      )}
      <div
        role="treeitem"
        aria-expanded={node.type === "folder" ? isExpanded : undefined}
        aria-selected={isSelected}
        aria-level={depth + 1}
        aria-label={node.name}
        tabIndex={isTreeTabStop ? 0 : -1}
        className={`group relative flex cursor-pointer items-center px-2 py-1 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary ${
          isDropTarget
            ? "bg-primary/10 text-primary ring-1 ring-inset ring-primary/20"
            : isSelected
              ? "bg-primary/15 text-primary"
              : "hover:bg-surface-sunken text-content-muted hover:text-content "
        } ${isDraggingThisNode ? "ring-1 ring-inset ring-primary/40" : ""}`}
        style={{ paddingLeft: `${depth * 0.875 + 0.5}rem` }}
        onClick={(event) => handleSelect(event.currentTarget)}
        onKeyDown={handleKeyDown}
        onFocus={(event) => {
          if (event.target !== event.currentTarget) {
            return;
          }
          focusTreeItem(event.currentTarget);
          if (draggingPath && canAcceptDrop && isKeyboardMoveActive(event.currentTarget)) {
            onDragTargetChange(dropTargetKey);
          }
        }}
        draggable={isDraggable}
        onDragStart={(event) => {
          finishKeyboardMove(event.currentTarget);
          if (isQaNode && qaNodeId) {
            event.stopPropagation();
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", qaNodeDragPath(qaNodeId));
            onDragStart(node);
            return;
          }
          if (isQaEntry && qaNodeId) {
            event.stopPropagation();
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData(
              "text/plain",
              qaEntryDragPath(qaNodeId, node.qaEntryQuestion ?? node.name),
            );
            onDragStart(node);
            return;
          }
          if (node.type !== "file" || node.virtual) return;
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", node.path);
          onDragStart(node);
        }}
        onDragEnd={(event) => {
          finishKeyboardMove(event.currentTarget);
          onDragEnd();
        }}
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
              className={`material-symbols-outlined text-[1rem] text-content-subtle transition-transform duration-150 ${isExpanded ? "rotate-90" : ""}`}
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
              node.name.endsWith(".md") ? "text-sky-400" : "text-content-subtle"
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
          <div className={QA_ACTIONS_OVERLAY_CLASS}>
            {onOrderQaNode && (
              <TreeActionButton
                title="調整順序與可見性"
                icon="sort"
                onClick={() => onOrderQaNode(null)}
              />
            )}
            <TreeActionButton
              title="新增快速問答節點"
              icon="add"
              variant="primary"
              onClick={() => onCreateQaNode(null)}
            />
          </div>
        )}

        {isQaNode && qaNodeId && (
          <div className={QA_ACTIONS_OVERLAY_CLASS}>
            {onToggleQaNodeHidden && (
              <TreeActionButton
                title={node.qaHidden ? "顯示節點" : "隱藏節點"}
                icon={node.qaHidden ? "visibility_off" : "visibility"}
                onClick={() => onToggleQaNodeHidden(qaNodeId, !node.qaHidden)}
              />
            )}
            {onOrderQaNode && (
              <TreeActionButton
                title="調整子節點順序與可見性"
                icon="sort"
                onClick={() => onOrderQaNode(qaNodeId)}
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

        {isDraggable && (
          <TreeActionButton
            title="使用鍵盤移動"
            icon="drive_file_move"
            onClick={(event) => {
              const tree = event.currentTarget.closest<HTMLElement>('[role="tree"]');
              if (tree) {
                tree.dataset.keyboardMove = "true";
              }
              onDragStart(node);
              onDragTargetChange(null);
              const treeItem = event.currentTarget.closest<HTMLElement>('[role="treeitem"]');
              focusTreeItem(treeItem ?? undefined);
            }}
          />
        )}

        {canDeleteFolder && (
          <button
            type="button"
            aria-label={`刪除資料夾 ${node.path}`}
            className="ml-1 shrink-0 rounded-md p-1 text-content-subtle opacity-0 transition-colors hover:bg-red-500/10 hover:text-red-400 focus:opacity-100 group-hover:opacity-100"
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
        <div role="group">
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
              onOrderQaNode={onOrderQaNode}
              canDropQaNode={canDropQaNode}
              canDropQaEntry={canDropQaEntry}
            />
          ))}
        </div>
      )}
      {depth === 0 && (
        <span className="sr-only" role="status" aria-live="polite">
          {draggingPath
            ? "移動模式已啟用。請巡覽至有效目標，按 Enter 或空白鍵放置，按 Escape 取消。"
            : ""}
        </span>
      )}
    </div>
  );
}

import { useId, useRef } from "react";
import type { DragEvent, KeyboardEvent } from "react";

import ActionMenu, { type ActionMenuGroup, type ActionMenuItem } from "../ActionMenu";
import type { QaDropPosition, TreeNode } from "./helpers";
import {
  collectBatchSelectableFiles,
  DOCUMENTS_ROOT_PATH,
  isBatchSelectableFile,
  parseQaEntryDragPath,
  parseQaNodeDragPath,
  qaDropPositionAt,
  qaEntryDragPath,
  qaNodeDragPath,
  qaTreeNodePath,
  splitFileNameForDisplay,
} from "./helpers";
import StatusDot, { documentStatusLabel } from "./StatusDot";

// 操作按鈕佔自己的寬度，名稱不會被蓋住，也就不會按名稱卻按到按鈕。
const TOUCH_TARGET_CLASS = "[@media(hover:none)]:p-1.5";
const ROW_ACTION_CLASS = `flex items-center justify-center rounded-md p-0.5 transition-colors ${TOUCH_TARGET_CLASS}`;
const MENU_TRIGGER_CLASS = `${ROW_ACTION_CLASS} text-content-subtle hover:bg-surface-sunken hover:text-content`;
// 用 invisible 而不是透明：別的列的按鈕才不在 Tab 順序裡，整棵樹只佔一個 Tab 停留點。
const REVEAL_WITH_ROW_CLASS =
  "invisible group-hover:visible group-focus-within:visible aria-expanded:visible [@media(hover:none)]:visible";

// 非中文文件在樹狀清單上的語言徽章。
const TREE_LANGUAGE_BADGES: Record<string, string> = { nan: "台", ja: "日", ko: "韓" };

interface TreeViewProps {
  node: TreeNode;
  selectedPath: string;
  expandedDirs: Set<string>;
  onSelect: (node: TreeNode) => void;
  onToggle: (path: string) => void;
  draggingPath: string | null;
  sourceDragDir: string;
  dropTargetPath: string | null;
  dropPosition?: QaDropPosition | null;
  onDragStart: (node: TreeNode) => void;
  onDragEnd: () => void;
  onDragTargetChange: (path: string | null, position?: QaDropPosition | null) => void;
  onDropFile: (targetDir: string, position?: QaDropPosition) => void;
  onDeleteFolder: (path: string) => void;
  onMoveFile?: (path: string) => void;
  onDeleteFile?: (path: string) => void;
  onSelectQaNode?: (nodeId: string, question?: string) => void;
  onCreateQaNode?: (parentNodeId: string | null) => void;
  onRenameQaNode?: (nodeId: string) => void;
  onMoveQaNode?: (nodeId: string) => void;
  onToggleQaNodeHidden?: (nodeId: string, hidden: boolean) => void;
  onDeleteQaNode?: (nodeId: string) => void;
  onOrderQaNode?: (parentNodeId: string | null) => void;
  canDropQaNode?: (draggedPath: string, targetPath: string, position?: QaDropPosition) => boolean;
  canDropQaEntry?: (draggedPath: string, targetPath: string) => boolean;
  multiSelect?: boolean;
  checkedPaths?: ReadonlySet<string>;
  onToggleChecked?: (paths: string[], checked: boolean) => void;
}

type SharedTreeProps = Omit<TreeViewProps, "node">;

function isSectionRow(node: TreeNode): boolean {
  return node.treeKind === "qa-root" || node.treeKind === "documents-root";
}

function hasVisibleSelectedNode(
  node: TreeNode,
  selectedPath: string,
  expandedDirs: Set<string>,
): boolean {
  if (!isSectionRow(node) && node.path === selectedPath) {
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

function compactItems(
  items: Array<ActionMenuItem | false | undefined | null>,
): ActionMenuItem[] {
  return items.filter((item): item is ActionMenuItem => Boolean(item));
}

function buildRowMenu(node: TreeNode, actions: SharedTreeProps): ActionMenuGroup[] {
  const {
    onCreateQaNode,
    onRenameQaNode,
    onMoveQaNode,
    onOrderQaNode,
    onToggleQaNodeHidden,
    onDeleteQaNode,
    onDeleteFolder,
    onMoveFile,
    onDeleteFile,
  } = actions;
  const nodeId = node.qaNodeId;

  if (node.treeKind === "qa-root") {
    return [{
      id: "section",
      items: compactItems([
        onCreateQaNode && {
          id: "create",
          label: "新增分類",
          onSelect: () => onCreateQaNode(null),
        },
        onOrderQaNode && {
          id: "order",
          label: "調整順序",
          onSelect: () => onOrderQaNode(null),
        },
      ]),
    }];
  }

  if (node.treeKind === "qa-node" && nodeId) {
    return [
      {
        id: "edit",
        items: compactItems([
          onCreateQaNode && {
            id: "create",
            label: "新增子分類",
            onSelect: () => onCreateQaNode(nodeId),
          },
          onRenameQaNode && {
            id: "rename",
            label: "重新命名",
            onSelect: () => onRenameQaNode(nodeId),
          },
          onMoveQaNode && {
            id: "move",
            label: "移到…",
            onSelect: () => onMoveQaNode(nodeId),
          },
          onOrderQaNode && {
            id: "order",
            label: "調整子分類順序",
            onSelect: () => onOrderQaNode(nodeId),
          },
          onToggleQaNodeHidden && {
            id: "visibility",
            label: node.qaHidden ? "顯示（訪客看得到）" : "隱藏（訪客看不到）",
            onSelect: () => onToggleQaNodeHidden(nodeId, !node.qaHidden),
          },
        ]),
      },
      {
        id: "danger",
        items: compactItems([
          onDeleteQaNode && {
            id: "delete",
            label: "刪除",
            danger: true,
            onSelect: () => onDeleteQaNode(nodeId),
          },
        ]),
      },
    ];
  }

  if (node.path === DOCUMENTS_ROOT_PATH || node.virtual) {
    return [];
  }

  if (node.type === "folder") {
    return [{
      id: "danger",
      items: [{
        id: "delete-folder",
        label: "刪除資料夾",
        danger: true,
        onSelect: () => onDeleteFolder(node.path),
      }],
    }];
  }

  // 核心文件不能移也不能刪。掛在快速問答上的文件要從分類處理，這裡只留刪除，
  // 規則與文件檢視相同。
  if (node.doc?.is_core) {
    return [];
  }
  const isQaAttached = node.doc?.source_type === "qa" && node.doc.qa_attached === true;
  return [
    {
      id: "edit",
      items: compactItems([
        onMoveFile && !isQaAttached && {
          id: "move",
          label: "移動…",
          onSelect: () => onMoveFile(node.path),
        },
      ]),
    },
    {
      id: "danger",
      items: compactItems([
        onDeleteFile && {
          id: "delete",
          label: "刪除",
          danger: true,
          onSelect: () => onDeleteFile(node.path),
        },
      ]),
    },
  ];
}

function rowIcon(node: TreeNode, isExpanded: boolean): { name: string; className: string } {
  if (node.treeKind === "qa-root") {
    return { name: "quiz", className: "text-primary" };
  }
  if (node.treeKind === "qa-entry") {
    return { name: "help", className: "text-content-subtle" };
  }
  if (node.type === "folder") {
    return { name: isExpanded ? "folder_open" : "folder", className: "text-primary/70" };
  }
  return node.name.endsWith(".md")
    ? { name: "markdown", className: "text-info" }
    : { name: "description", className: "text-content-subtle" };
}

function RowName({
  node,
  emphasized,
}: {
  node: TreeNode;
  emphasized: boolean;
}) {
  // 問題與分類名稱看開頭就認得出來；檔名常常只差結尾，所以只有檔案列留結尾。
  const isFileRow = node.type === "file" && !node.virtual;
  const { head, tail } = isFileRow
    ? splitFileNameForDisplay(node.name)
    : { head: node.name, tail: "" };

  return (
    <span
      title={node.name}
      className={`ml-1.5 flex min-w-0 flex-1 text-sm ${emphasized ? "font-semibold" : ""} ${
        node.qaHidden ? "opacity-60" : ""
      }`}
    >
      {/* 窄的樹上連結尾都放不下時，開頭先讓光，結尾再從左邊裁：副檔名和最後幾個字一定看得到。 */}
      <span className={`truncate whitespace-pre ${tail ? "shrink-[1000]" : ""}`}>{head}</span>
      {tail && <span className="flex min-w-0 justify-end overflow-hidden whitespace-pre">{tail}</span>}
    </span>
  );
}

function questionCountLabel(node: TreeNode): string | null {
  if (node.treeKind !== "qa-node" || node.qaQuestionCount === undefined) return null;
  // 只放子分類的上層沒有自己的題目，寫「0 題」會讓人以為底下是空的。
  const hasChildCategories = node.children.some((child) => child.treeKind === "qa-node");
  if (node.qaQuestionCount === 0 && hasChildCategories) return null;
  return `${node.qaQuestionCount} 題`;
}

function TreeBranch({
  node,
  depth,
  fallbackTabStopPath,
  ...shared
}: SharedTreeProps & {
  node: TreeNode;
  depth: number;
  fallbackTabStopPath: string | null;
}) {
  const {
    selectedPath,
    expandedDirs,
    onSelect,
    onToggle,
    draggingPath,
    sourceDragDir,
    dropTargetPath,
    dropPosition = null,
    onDragStart,
    onDragEnd,
    onDragTargetChange,
    onDropFile,
    onSelectQaNode,
    onCreateQaNode,
    canDropQaNode,
    canDropQaEntry,
    multiSelect = false,
    checkedPaths,
    onToggleChecked,
  } = shared;
  const rowRef = useRef<HTMLDivElement>(null);
  const isExpanded = expandedDirs.has(node.path);
  const isSection = isSectionRow(node);
  // 段落列只是分段標題：預設的 selectedPath 就是 knowledge，不該一進來就亮著。
  const isSelected = !isSection && selectedPath === node.path;
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
  const isDraggable = !multiSelect &&
    ((node.type === "file" && !node.virtual && !node.doc?.is_core) || isQaNode || isQaEntry);
  const isCheckableFile = multiSelect && isBatchSelectableFile(node);
  const folderFiles = multiSelect && node.type === "folder" && !node.virtual
    ? collectBatchSelectableFiles(node)
    : [];
  const checkedFolderFileCount = folderFiles.filter((path) => checkedPaths?.has(path)).length;
  const isChecked = isCheckableFile
    ? !!checkedPaths?.has(node.path)
    : folderFiles.length > 0 && checkedFolderFileCount === folderFiles.length;
  const isPartiallyChecked = checkedFolderFileCount > 0 && !isChecked;
  const showCheckbox = isCheckableFile || folderFiles.length > 0;
  const toggleChecked = () => {
    if (!onToggleChecked) return;
    onToggleChecked(isCheckableFile ? [node.path] : folderFiles, !isChecked);
  };
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
      ? ((isQaRoot || isQaNode) && !!canDropQaNode && canDropQaNode(draggingPath, dropTargetKey))
      : draggingQaEntry
        ? (isQaEntry && !!canDropQaEntry && canDropQaEntry(draggingPath, dropTargetKey))
      : (isQaRoot || isQaNode || isQaEntry || (!node.virtual && effectiveDropDir !== sourceDragDir)));
  const isDropTarget = dropTargetPath === dropTargetKey && !!draggingPath;
  const showInsertLine = isDropTarget && !!draggingQaNodeId &&
    (dropPosition === "before" || dropPosition === "after");
  const isTreeTabStop = isSelected || node.path === fallbackTabStopPath;

  // 先把焦點放回列上再開對話框：對話框關閉時會還原焦點，而「⋯」在列沒有焦點時
  // 是隱藏的，還原到它會失敗，鍵盤使用者就找不到剛才的位置。
  const menuGroups: ActionMenuGroup[] = multiSelect
    ? []
    : buildRowMenu(node, shared).map((group) => ({
        ...group,
        items: group.items.map((item) => ({
          ...item,
          onSelect: () => {
            rowRef.current?.focus();
            item.onSelect();
          },
        })),
      }));
  const hasMenu = menuGroups.some((group) => group.items.length > 0);
  const showAddCategory = isQaRoot && !!onCreateQaNode && !multiSelect;
  const questionCount = questionCountLabel(node);
  const statusLabel = node.doc && !node.virtual ? documentStatusLabel(node.doc) : null;
  const rowLabel = [
    node.name,
    node.qaLanguageCategory ? "語言分類" : null,
    questionCount,
    node.qaHidden ? "已隱藏" : null,
    statusLabel === "可被搜尋" ? null : statusLabel,
  ].filter(Boolean).join("，");

  const handleSelect = (treeItem: HTMLElement) => {
    if (draggingPath && isKeyboardMoveActive(treeItem)) {
      if (isDraggingThisNode) {
        finishKeyboardMove(treeItem);
        onDragEnd();
      } else if (canAcceptDrop) {
        finishKeyboardMove(treeItem);
        if (draggingQaNodeId) {
          // 鍵盤沒有游標位置，分類一律當作放進去。
          onDragTargetChange(dropTargetKey, "into");
          onDropFile(dropTargetKey, "into");
        } else {
          onDragTargetChange(dropTargetKey);
          onDropFile(dropTargetKey);
        }
      }
      return;
    }
    // 多選只作用在文件：點列只切換勾選或展開，不開檔，也不開快速問答，
    // 手機版檔案樹也不會因此收起。
    if (multiSelect) {
      if (isCheckableFile) toggleChecked();
      else if (node.type === "folder") onToggle(node.path);
      return;
    }
    if (isQaRoot) {
      onToggle(node.path);
      return;
    }
    if (isQaEntry && qaNodeId && onSelectQaNode) {
      onSelectQaNode(qaNodeId, node.qaEntryQuestion ?? node.name);
      return;
    }
    if (isQaNode && qaNodeId && onSelectQaNode) {
      onSelectQaNode(qaNodeId);
      // 只放子分類的上層自己沒有題目，右邊是空的；不展開的話使用者會以為什麼都沒有。
      if (!isExpanded && node.children.some((child) => child.treeKind === "qa-node")) {
        onToggle(node.path);
      }
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

  // 只有分類拖到分類才看游標位置；文件、問題不分區，拖回最上層一律是放進去。
  const pointerDropPosition = (event: DragEvent<HTMLDivElement>): QaDropPosition | null => {
    if (!draggingQaNodeId) return null;
    if (!isQaNode) return "into";
    return qaDropPositionAt(event.clientY, event.currentTarget.getBoundingClientRect());
  };
  const canDropAt = (position: QaDropPosition | null): boolean =>
    position !== "into" ||
    !isQaNode ||
    !draggingPath ||
    !canDropQaNode ||
    canDropQaNode(draggingPath, dropTargetKey, "into");
  const trackDropTarget = (event: DragEvent<HTMLDivElement>) => {
    if (!canAcceptDrop) return;
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "move";
    }
    const position = pointerDropPosition(event);
    if (canDropAt(position)) {
      onDragTargetChange(dropTargetKey, position);
    } else {
      onDragTargetChange(null);
    }
  };

  let rowStateClass: string;
  if (isDropTarget && !showInsertLine) {
    rowStateClass = "bg-primary/10 text-primary ring-1 ring-inset ring-primary/20";
  } else if (isSelected && !multiSelect) {
    rowStateClass = "bg-primary/15 text-primary";
  } else if (isCheckableFile && isChecked) {
    rowStateClass = "bg-primary/10 text-content";
  } else if (isSection) {
    rowStateClass = "text-content hover:bg-surface-sunken";
  } else {
    rowStateClass = "hover:bg-surface-sunken text-content-muted hover:text-content";
  }
  const icon = rowIcon(node, isExpanded);
  const rowIndentRem = depth * 0.875 + 0.5;

  return (
    <div
      role="none"
      className={node.treeKind === "documents-root" ? "mt-1 border-t border-border pt-1" : undefined}
    >
      <div
        ref={rowRef}
        role="treeitem"
        aria-expanded={node.type === "folder" ? isExpanded : undefined}
        aria-selected={isCheckableFile ? isChecked : isSelected}
        aria-level={depth + 1}
        aria-label={rowLabel}
        data-drop-position={isDropTarget ? dropPosition ?? "into" : undefined}
        tabIndex={isTreeTabStop ? 0 : -1}
        className={`group relative flex cursor-pointer items-center px-2 py-1 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary [@media(hover:none)]:py-1.5 ${rowStateClass} ${
          isDraggingThisNode ? "ring-1 ring-inset ring-primary/40" : ""
        }`}
        style={{ paddingLeft: `${rowIndentRem}rem` }}
        onClick={(event) => handleSelect(event.currentTarget)}
        onKeyDown={handleKeyDown}
        onFocus={(event) => {
          if (event.target !== event.currentTarget) {
            return;
          }
          focusTreeItem(event.currentTarget);
          if (draggingPath && canAcceptDrop && isKeyboardMoveActive(event.currentTarget)) {
            onDragTargetChange(dropTargetKey, draggingQaNodeId ? "into" : null);
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
        onDragOver={trackDropTarget}
        onDragEnter={trackDropTarget}
        onDragLeave={(event) => {
          // 移到列內的子元素也會觸發 dragleave，不算離開。
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
          if (isDropTarget) onDragTargetChange(null);
        }}
        onDrop={(event) => {
          if (!canAcceptDrop) return;
          const position = pointerDropPosition(event);
          if (!canDropAt(position)) return;
          event.preventDefault();
          event.stopPropagation();
          if (position) {
            onDropFile(dropTargetKey, position);
          } else {
            onDropFile(dropTargetKey);
          }
        }}
      >
        {showInsertLine && (
          <span
            aria-hidden="true"
            className={`pointer-events-none absolute right-1 z-[1] h-0.5 rounded-full bg-primary ${
              dropPosition === "before" ? "top-0 -translate-y-1/2" : "bottom-0 translate-y-1/2"
            }`}
            style={{ left: `${rowIndentRem}rem` }}
          />
        )}

        <div
          className="flex h-4 w-4 shrink-0 items-center justify-center [@media(hover:none)]:h-7 [@media(hover:none)]:w-7"
          onClick={node.type === "folder"
            ? (event) => {
                event.stopPropagation();
                onToggle(node.path);
              }
            : undefined}
        >
          {node.type === "folder" ? (
            <span
              aria-hidden="true"
              className={`material-symbols-outlined text-[1rem] text-content-subtle transition-transform duration-150 ${isExpanded ? "rotate-90" : ""}`}
            >
              chevron_right
            </span>
          ) : null}
        </div>

        {showCheckbox && (
          <input
            type="checkbox"
            tabIndex={-1}
            aria-label={node.type === "folder" ? `選取 ${node.name} 內的所有檔案` : `選取 ${node.name}`}
            checked={isChecked}
            ref={(element) => {
              if (element) element.indeterminate = isPartiallyChecked;
            }}
            onClick={(event) => event.stopPropagation()}
            onChange={toggleChecked}
            className="ml-0.5 h-3.5 w-3.5 shrink-0 accent-primary"
          />
        )}

        <div className="ml-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
          <span aria-hidden="true" className={`material-symbols-outlined text-[1.125rem] ${icon.className}`}>
            {icon.name}
          </span>
        </div>

        <RowName node={node} emphasized={isSection || isSelected} />

        {node.qaLanguageCategory && (
          <span aria-hidden="true" className="ml-1 shrink-0 whitespace-nowrap rounded bg-surface-sunken px-1 text-xs text-content-muted">
            語言
          </span>
        )}

        {questionCount && (
          <span className="ml-1 shrink-0 whitespace-nowrap text-xs text-content-subtle">
            {questionCount}
          </span>
        )}
        {node.qaHidden && (
          <span className="ml-1 shrink-0 whitespace-nowrap rounded bg-surface-sunken px-1 text-xs text-content-muted">
            已隱藏
          </span>
        )}

        {node.type === "file" && node.doc && !node.virtual && (
          <div className="ml-1 flex shrink-0 items-center gap-1">
            {/* 中文是預設，只標出英西版本，免得整棵樹都是 ZH。 */}
            {node.doc.language && node.doc.language !== "zh" && (
              <span className="rounded px-1 text-xs font-semibold uppercase text-content-subtle ring-1 ring-border">
                {TREE_LANGUAGE_BADGES[node.doc.language] ?? node.doc.language}
              </span>
            )}
            <StatusDot doc={node.doc} />
          </div>
        )}

        {(showAddCategory || hasMenu) && (
          // 選單用 portal 畫在 body，點選單項目的事件仍會沿 React 樹冒泡到這一列，
          // 不擋的話選「刪除」也會同時選取這一列。
          <div
            className="ml-0.5 flex shrink-0 items-center gap-0.5"
            onClick={(event) => event.stopPropagation()}
          >
            {showAddCategory && (
              <button
                type="button"
                className={`${ROW_ACTION_CLASS} gap-0.5 whitespace-nowrap pr-1 text-xs font-medium text-content hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary`}
                onClick={() => onCreateQaNode?.(null)}
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[1rem] leading-none text-primary">
                  add
                </span>
                新增分類
              </button>
            )}
            {hasMenu && (
              <ActionMenu
                label={node.name}
                groups={menuGroups}
                triggerClassName={`${MENU_TRIGGER_CLASS} ${isSelected ? "" : REVEAL_WITH_ROW_CLASS}`}
              />
            )}
          </div>
        )}

        {isDraggable && (
          <button
            type="button"
            className="invisible sr-only group-focus-within:visible focus:not-sr-only focus:ml-1 focus:shrink-0 focus:whitespace-nowrap focus:rounded-md focus:bg-surface-sunken focus:px-1.5 focus:py-0.5 focus:text-xs focus:text-content"
            onClick={(event) => {
              event.stopPropagation();
              const tree = event.currentTarget.closest<HTMLElement>('[role="tree"]');
              if (tree) {
                tree.dataset.keyboardMove = "true";
              }
              onDragStart(node);
              onDragTargetChange(null);
              const treeItem = event.currentTarget.closest<HTMLElement>('[role="treeitem"]');
              focusTreeItem(treeItem ?? undefined);
            }}
          >
            使用鍵盤移動
          </button>
        )}
      </div>

      {isSection && isExpanded && node.children.length === 0 && !multiSelect && (
        <p
          className="py-1.5 pr-2 text-xs text-content-subtle"
          style={{ paddingLeft: `${rowIndentRem + 1.5}rem` }}
        >
          {isQaRoot ? "還沒有分類。按上面的「新增分類」開始。" : "還沒有文件。按頁首的「新增資料」加入。"}
        </p>
      )}

      {node.type === "folder" && isExpanded && node.children.length > 0 && (
        <div role="group">
          {node.children.map((child) => (
            <TreeBranch
              key={child.path}
              node={child}
              depth={depth + 1}
              fallbackTabStopPath={fallbackTabStopPath}
              {...shared}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function TreeView({ node, ...shared }: TreeViewProps) {
  const instructionsId = useId();
  const { selectedPath, expandedDirs, draggingPath, multiSelect = false } = shared;
  // 兩個段落共用一棵樹：只有一個 role="tree"，aria-level 從段落列算起。
  const roots = node.treeKind === "sections" ? node.children : [node];
  const hasVisibleSelection = roots.some((root) =>
    hasVisibleSelectedNode(root, selectedPath, expandedDirs),
  );
  const fallbackTabStopPath = hasVisibleSelection ? null : roots[0]?.path ?? null;

  return (
    <div
      role="tree"
      aria-label="知識庫目錄"
      aria-describedby={instructionsId}
      aria-multiselectable={multiSelect ? true : undefined}
    >
      <span id={instructionsId} className="sr-only">
        {multiSelect
          ? "多選模式：使用方向鍵巡覽，Enter 或空白鍵選取或取消選取檔案。"
          : "使用方向鍵巡覽，Enter 或空白鍵開啟。選擇「使用鍵盤移動」後，移至目標並按 Enter 或空白鍵放置，Escape 取消。"}
      </span>
      {roots.map((root) => (
        <TreeBranch
          key={root.path}
          node={root}
          depth={0}
          fallbackTabStopPath={fallbackTabStopPath}
          {...shared}
        />
      ))}
      <span className="sr-only" role="status" aria-live="polite">
        {draggingPath
          ? "移動模式已啟用。請巡覽至有效目標，按 Enter 或空白鍵放置，按 Escape 取消。"
          : ""}
      </span>
    </div>
  );
}

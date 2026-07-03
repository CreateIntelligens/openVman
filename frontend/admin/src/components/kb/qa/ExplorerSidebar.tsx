import { type DragEvent, type MouseEvent, useMemo, useState } from "react";

import type { QaNode } from "../../../hooks/useQaNodes";
import ConfirmModal from "../../ConfirmModal";
import PromptModal from "../../PromptModal";

type NodeUpdate = { label?: string; hidden?: boolean };
type NodeAction = Promise<unknown>;

type NodeDialog =
  | { type: "add-root" }
  | { type: "add-child"; node: QaNode }
  | { type: "rename"; node: QaNode }
  | { type: "delete"; node: QaNode };

interface SidebarNodeItemProps {
  node: QaNode;
  depth: number;
  parentId: string | null;
  siblings: QaNode[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onRequestAddChild: (node: QaNode) => void;
  onRequestRename: (node: QaNode) => void;
  onRequestDelete: (node: QaNode) => void;
  onUpdateNode: (id: string, updates: NodeUpdate) => NodeAction;
  onReorderNode: (id: string, siblingIdsOrdered: string[]) => NodeAction;
  expandedNodeIds: Set<string>;
  toggleExpand: (nodeId: string) => void;
  draggedNodeId: string | null;
  setDraggedNodeId: (id: string | null) => void;
  draggedParentId: string | null;
  setDraggedParentId: (id: string | null) => void;
  search: string;
}

function SidebarNodeItem({
  node,
  depth,
  parentId,
  siblings,
  selectedNodeId,
  onSelectNode,
  onRequestAddChild,
  onRequestRename,
  onRequestDelete,
  onUpdateNode,
  onReorderNode,
  expandedNodeIds,
  toggleExpand,
  draggedNodeId,
  setDraggedNodeId,
  draggedParentId,
  setDraggedParentId,
  search,
}: SidebarNodeItemProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const isSelected = selectedNodeId === node.node_id;
  const children = node.children ?? [];
  const hasChildren = children.length > 0;
  const isExpanded = search ? true : expandedNodeIds.has(node.node_id);
  let itemStateClass =
    "hover:bg-slate-100 dark:hover:bg-slate-800/60 text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white";

  if (isDragOver) {
    itemStateClass = "bg-info/10 dark:bg-info/20 border-info/50";
  } else if (isSelected) {
    itemStateClass = "bg-primary/10 text-primary font-medium";
  }

  const handleToggle = (e: MouseEvent) => {
    e.stopPropagation();
    toggleExpand(node.node_id);
  };

  const handleDragStart = (e: DragEvent) => {
    e.stopPropagation();
    setDraggedNodeId(node.node_id);
    setDraggedParentId(parentId);
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDragEnd = () => {
    setDraggedNodeId(null);
    setDraggedParentId(null);
  };

  const handleDragOver = (e: DragEvent) => {
    if (draggedParentId === parentId && draggedNodeId !== node.node_id) {
      e.preventDefault();
      setIsDragOver(true);
    }
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (draggedNodeId && draggedParentId === parentId && draggedNodeId !== node.node_id) {
      const siblingIds = siblings.map((s) => s.node_id);
      const dragIdx = siblingIds.indexOf(draggedNodeId);
      const targetIdx = siblingIds.indexOf(node.node_id);
      if (dragIdx !== -1 && targetIdx !== -1) {
        const newOrdered = [...siblingIds];
        newOrdered.splice(dragIdx, 1);
        const insertIdx = newOrdered.indexOf(node.node_id);
        newOrdered.splice(insertIdx, 0, draggedNodeId);
        onReorderNode(draggedNodeId, newOrdered);
      }
    }
  };

  const handleAddChild = (e: MouseEvent) => {
    e.stopPropagation();
    onRequestAddChild(node);
  };

  const handleEditLabel = (e: MouseEvent) => {
    e.stopPropagation();
    onRequestRename(node);
  };

  const handleDeleteClick = (e: MouseEvent) => {
    e.stopPropagation();
    onRequestDelete(node);
  };

  const handleToggleVisibility = (e: MouseEvent) => {
    e.stopPropagation();
    onUpdateNode(node.node_id, { hidden: !node.hidden });
  };

  return (
    <div className="flex flex-col select-none">
      <div
        className={`group flex items-center py-1.5 px-3 cursor-pointer transition-all duration-150 border border-transparent rounded-lg ${itemStateClass}`}
        style={{ paddingLeft: `${depth * 0.875 + 0.75}rem` }}
        onClick={() => onSelectNode(node.node_id)}
        draggable
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <span
          className="material-symbols-outlined text-[1.25rem] text-slate-400 dark:text-slate-500 cursor-grab active:cursor-grabbing mr-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
          title="拖曳以排序"
        >
          drag_indicator
        </span>

        <div className="w-5 h-5 flex items-center justify-center shrink-0 mr-1" onClick={handleToggle}>
          {hasChildren ? (
            <span
              className={`material-symbols-outlined text-[1.125rem] text-slate-500 transition-transform duration-150 hover:text-slate-700 dark:hover:text-slate-300 ${
                isExpanded ? "rotate-90" : ""
              }`}
            >
              chevron_right
            </span>
          ) : (
            <div className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600" />
          )}
        </div>

        <span className="material-symbols-outlined text-[1.125rem] text-amber-500/80 mr-1.5 shrink-0">
          {hasChildren ? (isExpanded ? "folder_open" : "folder") : "description"}
        </span>

        <span className={`text-[0.875rem] truncate flex-1 ${node.hidden ? "opacity-40" : ""}`}>
          {node.label}
        </span>

        <div className="flex items-center gap-1.5 ml-2 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          <button
            onClick={handleToggleVisibility}
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            title={node.hidden ? "顯示節點" : "隱藏節點"}
          >
            <span className="material-symbols-outlined text-[1.05rem]">
              {node.hidden ? "visibility_off" : "visibility"}
            </span>
          </button>

          <button
            onClick={handleAddChild}
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            title="新增子節點"
          >
            <span className="material-symbols-outlined text-[1.05rem]">add</span>
          </button>

          <button
            onClick={handleEditLabel}
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            title="修改名稱"
          >
            <span className="material-symbols-outlined text-[1.05rem]">edit</span>
          </button>

          <button
            onClick={handleDeleteClick}
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-red-500 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300"
            title="刪除節點"
          >
            <span className="material-symbols-outlined text-[1.05rem]">delete</span>
          </button>
        </div>
      </div>

      {hasChildren && isExpanded && (
        <div className="flex flex-col">
          {children.map((child) => (
            <SidebarNodeItem
              key={child.node_id}
              node={child}
              depth={depth + 1}
              parentId={node.node_id}
              siblings={children}
              selectedNodeId={selectedNodeId}
              onSelectNode={onSelectNode}
              onRequestAddChild={onRequestAddChild}
              onRequestRename={onRequestRename}
              onRequestDelete={onRequestDelete}
              onUpdateNode={onUpdateNode}
              onReorderNode={onReorderNode}
              expandedNodeIds={expandedNodeIds}
              toggleExpand={toggleExpand}
              draggedNodeId={draggedNodeId}
              setDraggedNodeId={setDraggedNodeId}
              draggedParentId={draggedParentId}
              setDraggedParentId={setDraggedParentId}
              search={search}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface ExplorerSidebarProps {
  nodesTree: QaNode[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onCreateNode: (
    nodeId: string,
    label: string,
    parentIds?: string[],
    childIds?: string[],
    order?: number,
    hidden?: boolean
  ) => NodeAction;
  onUpdateNode: (id: string, updates: NodeUpdate) => NodeAction;
  onDeleteNode: (id: string) => NodeAction;
  onReorderNode: (id: string, siblingIdsOrdered: string[]) => NodeAction;
  loading?: boolean;
  error?: string | null;
}

export default function ExplorerSidebar({
  nodesTree,
  selectedNodeId,
  onSelectNode,
  onCreateNode,
  onUpdateNode,
  onDeleteNode,
  onReorderNode,
  loading,
  error,
}: ExplorerSidebarProps) {
  const [search, setSearch] = useState("");
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(new Set());
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [draggedParentId, setDraggedParentId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<NodeDialog | null>(null);

  const closeDialog = () => setDialog(null);

  const handleCreateSubmit = (values: Record<string, string>) => {
    const parentIds = dialog?.type === "add-child" ? [dialog.node.node_id] : [];
    const nodeId = values.node_id || `node_${Date.now()}`;
    onCreateNode(nodeId, values.label, parentIds, [], 1.0, false);
    closeDialog();
  };

  const handleRenameSubmit = (values: Record<string, string>) => {
    if (dialog?.type === "rename" && values.label !== dialog.node.label) {
      onUpdateNode(dialog.node.node_id, { label: values.label });
    }
    closeDialog();
  };

  const handleDeleteConfirm = () => {
    if (dialog?.type === "delete") {
      onDeleteNode(dialog.node.node_id);
    }
    closeDialog();
  };

  const toggleExpand = (nodeId: string) => {
    setExpandedNodeIds((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  const handleAddRootNode = () => {
    setDialog({ type: "add-root" });
  };

  const handleExpandAll = () => {
    const allIds = new Set<string>();
    const visited = new Set<string>();
    const collectIds = (nodes: QaNode[]) => {
      nodes.forEach((n) => {
        if (visited.has(n.node_id)) return;
        visited.add(n.node_id);
        allIds.add(n.node_id);
        if (n.children) collectIds(n.children);
      });
    };
    collectIds(nodesTree);
    setExpandedNodeIds(allIds);
  };

  const handleCollapseAll = () => {
    setExpandedNodeIds(new Set());
  };

  const filteredTree = useMemo(() => {
    if (!search.trim()) return nodesTree;
    const lower = search.toLowerCase();

    const visited = new Set<string>();
    const filterNodes = (nodes: QaNode[]): QaNode[] => {
      return nodes.reduce<QaNode[]>((acc, node) => {
        if (visited.has(node.node_id)) return acc;
        visited.add(node.node_id);

        const childrenFiltered = node.children ? filterNodes(node.children) : [];
        const matchesSelf =
          node.label.toLowerCase().includes(lower) || node.node_id.toLowerCase().includes(lower);

        if (matchesSelf || childrenFiltered.length > 0) {
          acc.push({
            ...node,
            children: childrenFiltered,
          });
        }
        return acc;
      }, []);
    };

    return filterNodes(nodesTree);
  }, [nodesTree, search]);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 w-full">
      {error && (
        <div className="px-4 py-2 bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-xs border-b border-red-100 dark:border-red-900/30 flex items-center gap-1.5 shrink-0">
          <span className="material-symbols-outlined text-[1rem]">error</span>
          <span className="truncate flex-1">{error}</span>
        </div>
      )}
      <div className="p-4 flex flex-col gap-2 shrink-0 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate">問答知識節點</h3>
            {loading && (
              <span className="material-symbols-outlined text-[1rem] text-slate-400 dark:text-slate-500 animate-spin shrink-0">
                sync
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={handleAddRootNode}
              className="flex items-center gap-1 text-[0.75rem] font-medium py-1 px-2 text-primary hover:bg-primary/10 rounded transition-colors"
              title="新增根節點"
            >
              <span className="material-symbols-outlined text-[1rem]">add</span>
              根節點
            </button>
          </div>
        </div>

        <div className="relative">
          <input
            type="text"
            placeholder="搜尋節點名稱或 ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full text-xs pl-8 pr-3 py-1.5 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
          />
          <span className="material-symbols-outlined text-[1rem] absolute left-2.5 top-1.5 text-slate-400 dark:text-slate-500">
            search
          </span>
        </div>

        <div className="flex items-center gap-2 text-[0.7rem] text-slate-500 dark:text-slate-400 mt-1">
          <button onClick={handleExpandAll} className="hover:text-slate-700 dark:hover:text-slate-200 transition-colors">
            展開全部
          </button>
          <span>|</span>
          <button
            onClick={handleCollapseAll}
            className="hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
          >
            收合全部
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        {loading && filteredTree.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500 text-xs">
            <span className="material-symbols-outlined animate-spin mb-2 text-primary text-[1.5rem]">sync</span>
            載入中...
          </div>
        ) : filteredTree.length === 0 ? (
          <div className="text-center py-8 text-xs text-slate-400 dark:text-slate-500">
            {search ? "找不到相符的節點" : "尚無任何知識節點，請點擊上方按鈕建立"}
          </div>
        ) : (
          filteredTree.map((node) => (
            <SidebarNodeItem
              key={node.node_id}
              node={node}
              depth={0}
              parentId={null}
              siblings={nodesTree}
              selectedNodeId={selectedNodeId}
              onSelectNode={onSelectNode}
              onRequestAddChild={(target) => setDialog({ type: "add-child", node: target })}
              onRequestRename={(target) => setDialog({ type: "rename", node: target })}
              onRequestDelete={(target) => setDialog({ type: "delete", node: target })}
              onUpdateNode={onUpdateNode}
              onReorderNode={onReorderNode}
              expandedNodeIds={expandedNodeIds}
              toggleExpand={toggleExpand}
              draggedNodeId={draggedNodeId}
              setDraggedNodeId={setDraggedNodeId}
              draggedParentId={draggedParentId}
              setDraggedParentId={setDraggedParentId}
              search={search}
            />
          ))
        )}
      </div>

      <PromptModal
        open={dialog?.type === "add-root" || dialog?.type === "add-child"}
        title={dialog?.type === "add-child" ? `在「${dialog.node.label}」下新增子節點` : "新增根節點"}
        fields={[
          { key: "label", label: "節點名稱", placeholder: "請輸入名稱", required: true },
          {
            key: "node_id",
            label: "唯一識別碼",
            placeholder: "留空自動生成",
            hint: "限英文/數字/底線；留空自動生成",
          },
        ]}
        submitLabel="新增"
        onSubmit={handleCreateSubmit}
        onCancel={closeDialog}
      />

      <PromptModal
        open={dialog?.type === "rename"}
        title="修改節點名稱"
        fields={[
          {
            key: "label",
            label: "節點名稱",
            initialValue: dialog?.type === "rename" ? dialog.node.label : "",
            required: true,
          },
        ]}
        submitLabel="儲存"
        onSubmit={handleRenameSubmit}
        onCancel={closeDialog}
      />

      <ConfirmModal
        open={dialog?.type === "delete"}
        title="刪除節點"
        message={
          dialog?.type === "delete"
            ? `確定要刪除節點「${dialog.node.label}」嗎？\n注意：此操作無法復原，子節點將不會自動被刪除，但會與此節點脫鉤。`
            : ""
        }
        confirmLabel="刪除"
        danger
        onConfirm={handleDeleteConfirm}
        onCancel={closeDialog}
      />
    </div>
  );
}

import type { KnowledgeCommitFileResult } from "../../api";
import { isImportItemActive, type ImportItem } from "../../hooks/useKnowledgeImport";
import type { QaNode } from "../../hooks/useQaNodes";
import {
  DOCUMENTS_ROOT_PATH,
  findQaNode,
  formatSize,
  getQaNodeParentId,
  KNOWLEDGE_LANGUAGE_LABELS,
  parentDirOf,
  splitFileNameForDisplay,
} from "./helpers";

const ROW_BUTTON = "btn btn-ghost px-2.5 py-1 text-xs";

interface ImportResultListProps {
  items: ImportItem[];
  nodesTree: QaNode[];
  onViewDocument: (path: string) => void;
  onViewQaNode: (nodeId: string) => void;
  onRenameQaNode: (nodeId: string) => void;
  onRetry: (itemId: string) => void;
  onClear: () => void;
}

// 問答表不經過 AI，但從檔名分不出這份 CSV 是不是問答表，一律寫「處理中」才不會說錯。
function isMaybeQaTable(name: string): boolean {
  return /\.(csv|xlsx)$/i.test(name);
}

function activeLabel(item: ImportItem): string {
  if (item.state === "uploading") return "上傳中";
  if (item.state === "waiting") return "排隊中";
  return item.normalize && !isMaybeQaTable(item.name) ? "AI 整理中" : "處理中";
}

/** 問答的位置用目前的樹算：改名、移動之後這一列要跟著變。 */
function qaPlacement(result: KnowledgeCommitFileResult, nodesTree: QaNode[]) {
  const node = result.qa_node_id ? findQaNode(nodesTree, result.qa_node_id) : undefined;
  const parentId = node ? getQaNodeParentId(nodesTree, node.node_id) : null;
  const liveParentLabel = parentId ? findQaNode(nodesTree, parentId)?.label : undefined;
  const parentLabel = node ? liveParentLabel : result.qa_parent_label;
  const label = node?.label ?? result.qa_node_label;
  const place = [parentLabel, label].filter(Boolean).join(" › ");
  const count = result.question_count === undefined ? "" : `（${result.question_count} 題）`;
  return { nodeId: node?.node_id, text: `${place}${count}` };
}

function documentFolderNote(target: string): string {
  const folder = parentDirOf(target);
  if (!folder || folder === DOCUMENTS_ROOT_PATH) return "";
  const relative = folder.replace(`${DOCUMENTS_ROOT_PATH}/`, "");
  return `，放在「${relative.split("/").join(" › ")}」`;
}

/** 長檔名省略中間、留住結尾，分得出「_IMG_PRP_1.csv」和「_IMG_PRP_2.csv」。 */
export function ImportFileName({ name }: { name: string }) {
  const { head, tail } = splitFileNameForDisplay(name);
  return (
    <span title={name} className="flex min-w-0 text-sm font-medium text-content">
      <span className="truncate">{head}</span>
      {tail && <span className="shrink-0">{tail}</span>}
    </span>
  );
}

function ImportResultRow({
  item,
  nodesTree,
  onViewDocument,
  onViewQaNode,
  onRenameQaNode,
  onRetry,
}: Omit<ImportResultListProps, "items" | "onClear"> & { item: ImportItem }) {
  const active = isImportItemActive(item);
  const result = item.state === "done" ? item.result : undefined;
  const placement = result?.kind === "qa" ? qaPlacement(result, nodesTree) : null;
  const qaNodeId = placement?.nodeId;
  const language = result?.kind === "document" && result.language
    ? KNOWLEDGE_LANGUAGE_LABELS[result.language]
    : undefined;

  let icon = "check_circle";
  let iconClass = "text-success";
  let text: string;
  if (active) {
    icon = "progress_activity";
    iconClass = "animate-spin text-primary";
    text = activeLabel(item);
  } else if (item.state === "skipped") {
    icon = "error";
    iconClass = "text-warn";
    text = `沒有匯入：${item.message ?? ""}`;
  } else if (item.state === "failed") {
    icon = "error";
    iconClass = "text-danger";
    text = `沒有完成：${item.message ?? ""}`;
  } else if (placement) {
    const verb = result?.updated ? "已更新快速問答" : "已放進快速問答";
    text = placement.text ? `${verb}：${placement.text}` : verb;
  } else {
    const verb = result?.updated ? "已更新既有文件" : "已加入知識庫";
    text = `${verb}${result ? documentFolderNote(result.target) : ""}`;
  }

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
      <span aria-hidden="true" className={`material-symbols-outlined shrink-0 text-[1.25rem] ${iconClass}`}>
        {icon}
      </span>
      <div className="min-w-0 flex-1 basis-[60%]">
        <div className="flex min-w-0 items-baseline gap-2">
          <ImportFileName name={item.name} />
          {item.size !== undefined && (
            <span className="shrink-0 text-xs text-content-subtle">{formatSize(item.size)}</span>
          )}
        </div>
        <p className={`mt-0.5 break-words text-sm ${
          item.state === "failed"
            ? "text-danger"
            : item.state === "skipped"
              ? "text-content"
              : "text-content-muted"
        }`}
        >
          {text}
          {language && <span className="chip ml-2 align-middle">{language}</span>}
        </p>
      </div>
      {!active && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {result?.kind === "document" && (
            <button
              type="button"
              className={ROW_BUTTON}
              aria-label={`查看 ${item.name}`}
              onClick={() => onViewDocument(result.target)}
            >
              查看
            </button>
          )}
          {qaNodeId && (
            <>
              <button
                type="button"
                className={ROW_BUTTON}
                aria-label={`查看 ${item.name}`}
                onClick={() => onViewQaNode(qaNodeId)}
              >
                查看
              </button>
              <button
                type="button"
                className={ROW_BUTTON}
                aria-label={`改名 ${item.name}`}
                onClick={() => onRenameQaNode(qaNodeId)}
              >
                改名
              </button>
            </>
          )}
          {item.state !== "done" && item.rawPath && (
            <button
              type="button"
              className={ROW_BUTTON}
              aria-label={`再試一次 ${item.name}`}
              onClick={() => onRetry(item.id)}
            >
              再試一次
            </button>
          )}
        </div>
      )}
    </li>
  );
}

function summaryText(items: ImportItem[]): string {
  const activeCount = items.filter(isImportItemActive).length;
  if (activeCount > 0) {
    return `還有 ${activeCount} 個在處理。可以先去看別的文件，不用等在這裡。`;
  }
  const doneCount = items.filter((item) => item.state === "done").length;
  const notImported = items.length - doneCount;
  return notImported > 0
    ? `完成 ${doneCount} 個，${notImported} 個沒有匯入。`
    : `全部完成，共 ${doneCount} 個。`;
}

/** 這份清單留在畫面上直到使用者清除，上傳後看的就是這裡。 */
export default function ImportResultList({
  items,
  nodesTree,
  onViewDocument,
  onViewQaNode,
  onRenameQaNode,
  onRetry,
  onClear,
}: ImportResultListProps) {
  if (items.length === 0) return null;
  const canClear = items.some((item) => !isImportItemActive(item));

  return (
    <section aria-labelledby="knowledge-import-results" className="rounded-xl border border-border bg-surface-raised px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h3 id="knowledge-import-results" className="text-sm font-semibold text-content">匯入結果</h3>
          <p role="status" className="text-xs text-content-muted">{summaryText(items)}</p>
        </div>
        {canClear && (
          <button type="button" className={ROW_BUTTON} onClick={onClear}>
            清除結果
          </button>
        )}
      </div>
      <ul className="mt-1 divide-y divide-border">
        {items.map((item) => (
          <ImportResultRow
            key={item.id}
            item={item}
            nodesTree={nodesTree}
            onViewDocument={onViewDocument}
            onViewQaNode={onViewQaNode}
            onRenameQaNode={onRenameQaNode}
            onRetry={onRetry}
          />
        ))}
      </ul>
    </section>
  );
}

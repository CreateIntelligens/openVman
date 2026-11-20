import { useEffect, useMemo, useState } from "react";

import type {
  KnowledgeConflictDecision,
  KnowledgeFileDecision,
  KnowledgePreviewQaFile,
  KnowledgePreviewQuestion,
} from "../../api";
import type { QaNode } from "../../hooks/useQaNodes";
import { diffAnswers, type AnswerDiffPart } from "./answerDiff";
import { fileNameOf } from "./helpers";
import { ImportFileName } from "./ImportResultList";
import { useQaImageUpload } from "./qa/useQaImageUpload";
import QaImagePreview from "./QaImagePreview";

export interface QaUploadReviewFileItem {
  rawPath: string;
  name: string;
  itemId: string;
  size?: number;
  preview: KnowledgePreviewQaFile;
}

export interface QaUploadReviewProps {
  vendor?: boolean;
  files: QaUploadReviewFileItem[];
  /** 廠商畫面顯示用的分類名稱（node_id → 名稱）；`nodesTree` 要給原本的名稱，才對得上預覽。 */
  categoryLabels?: ReadonlyMap<string, string>;
  /** 同批一起上傳的一般文件（不用檢查，按匯入時一併送出）。 */
  documentPaths?: string[];
  nodesTree: QaNode[];
  onConfirm: (
    selectedQaPaths: string[],
    decisions: Record<string, KnowledgeFileDecision>,
  ) => void;
  onCancel: () => void;
  onError?: (message: string) => void;
}

const CONFLICT_OPTIONS: { value: KnowledgeConflictDecision; label: string }[] = [
  { value: "overwrite", label: "覆蓋" },
  { value: "keep", label: "保留原本" },
  { value: "both", label: "兩題都留（新的會先隱藏）" },
  { value: "later", label: "稍後調整" },
];

interface PlacementTreeNode {
  label: string;
  pathKey: string;
  depth: number;
  count: number;
  isNew: boolean;
  children: PlacementTreeNode[];
}

function normalizeLabelKey(label: string): string {
  return label.normalize("NFKC").trim().toLowerCase();
}

export function buildPlacementTree(
  questions: KnowledgePreviewQuestion[],
  existingTree: QaNode[],
  labelOf: (part: string, existing?: QaNode) => string = (part, existing) => existing?.label ?? part,
): PlacementTreeNode[] {
  const roots: PlacementTreeNode[] = [];

  for (const q of questions) {
    if (!q.placement || q.placement.length === 0) continue;
    let currentList = roots;
    let existingLevel: QaNode[] = existingTree;
    let pathPrefix = "";

    for (let index = 0; index < q.placement.length; index += 1) {
      const part = q.placement[index];
      const key = normalizeLabelKey(part);
      pathPrefix = pathPrefix ? `${pathPrefix}/${part}` : part;
      const existingMatch = existingLevel.find(
        (node) => normalizeLabelKey(node.label) === key,
      );
      let treeNode = currentList.find(
        (node) => normalizeLabelKey(node.label) === key,
      );
      if (!treeNode) {
        treeNode = {
          label: labelOf(part, existingMatch),
          pathKey: pathPrefix,
          depth: index,
          count: 0,
          isNew: !existingMatch,
          children: [],
        };
        currentList.push(treeNode);
      }
      if (index === q.placement.length - 1) {
        treeNode.count += 1;
      }
      currentList = treeNode.children;
      existingLevel = existingMatch?.children ?? [];
    }
  }

  return roots;
}

function flattenPlacementTree(nodes: PlacementTreeNode[]): PlacementTreeNode[] {
  const out: PlacementTreeNode[] = [];
  const walk = (list: PlacementTreeNode[]) => {
    for (const node of list) {
      out.push(node);
      walk(node.children);
    }
  };
  walk(nodes);
  return out;
}

function AnswerComparison({ question }: { question: KnowledgePreviewQuestion }) {
  const oldAnswer = question.old?.answer ?? "";
  const newAnswer = question.new?.answer ?? "";
  const [oldParts, newParts] = useMemo(() => diffAnswers(oldAnswer, newAnswer), [oldAnswer, newAnswer]);
  const sides = [
    { title: "原本的答案", side: question.old, parts: oldParts },
    { title: "新檔案的答案", side: question.new, parts: newParts },
  ];

  const renderPart = (part: AnswerDiffPart, index: number) => part.changed
    ? <mark key={index} className="rounded-sm bg-warn/25 text-content">{part.text}</mark>
    : part.text;

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {sides.map(({ title, side, parts }) => (
        <div key={title} className="min-w-0 rounded-lg border border-border bg-surface p-2.5 [overflow-wrap:anywhere]">
          <p className="text-xs font-medium text-content-muted">{title}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm text-content">
            {side?.answer ? parts.map(renderPart) : "（沒有文字答案）"}
          </p>
          {side?.image && <p className="mt-1 text-xs text-content-muted">圖片：{side.image}</p>}
          {side?.url && <p className="mt-1 text-xs text-content-muted">連結：{side.url}</p>}
        </div>
      ))}
    </div>
  );
}


function defaultSelectedMap(files: QaUploadReviewFileItem[]): Record<string, boolean> {
  const initial: Record<string, boolean> = {};
  for (const file of files) {
    initial[file.rawPath] = file.preview.errors.length === 0;
  }
  return initial;
}

export default function QaUploadReview({
  vendor = false,
  files,
  categoryLabels,
  documentPaths = [],
  nodesTree,
  onConfirm,
  onCancel,
  onError,
}: QaUploadReviewProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>(() =>
    defaultSelectedMap(files),
  );
  const [conflicts, setConflicts] = useState<
    Record<string, Record<string, KnowledgeConflictDecision>>
  >({});
  const [images, setImages] = useState<Record<string, Record<string, string>>>({});
  const [uploadError, setUploadError] = useState<string | null>(null);

  useEffect(() => {
    setSelected(defaultSelectedMap(files));
    setConflicts({});
    setImages({});
    setUploadError(null);
  }, [files]);

  const { uploadingRowId, pickImage, fileInputProps } = useQaImageUpload({
    onUploaded: (rowKey, imageId) => {
      const separator = rowKey.indexOf("::");
      if (separator < 0) return;
      const rawPath = rowKey.slice(0, separator);
      const imageValue = rowKey.slice(separator + 2);
      setUploadError(null);
      setImages((prev) => ({
        ...prev,
        [rawPath]: { ...(prev[rawPath] ?? {}), [imageValue]: imageId },
      }));
    },
    onError: (message) => {
      setUploadError(message);
      onError?.(message);
    },
  });

  const setConflictChoice = (
    rawPath: string,
    question: string,
    choice: KnowledgeConflictDecision,
  ) => {
    setConflicts((prev) => ({
      ...prev,
      [rawPath]: { ...(prev[rawPath] ?? {}), [question]: choice },
    }));
  };

  const importableFiles = files.filter((file) => file.preview.errors.length === 0);
  const conflictGroups = importableFiles.map(({ rawPath, preview }) => ({
    rawPath,
    questions: preview.questions.filter((q) => q.status === "conflict"),
  }));
  // 沒勾選的檔案不會匯入，它的重複題不用選。
  const missingChoices = conflictGroups.filter(({ rawPath }) => selected[rawPath]).reduce((count, { rawPath, questions }) =>
    count + questions.filter((q) => !Object.prototype.hasOwnProperty.call(conflicts[rawPath] ?? {}, q.question)).length, 0);
  const hasConflicts = conflictGroups.some(({ questions }) => questions.length > 0);

  const setAllConflicts = (choice: KnowledgeConflictDecision) => {
    setConflicts(Object.fromEntries(conflictGroups.map(({ rawPath, questions }) => [
      rawPath,
      Object.fromEntries(questions.map(({ question }) => [question, choice])),
    ])));
  };

  const selectedQaPaths = importableFiles.filter((file) => selected[file.rawPath]).map((file) => file.rawPath);
  const canImport = missingChoices === 0 && (selectedQaPaths.length > 0 || documentPaths.length > 0);

  const handleImportClick = () => {
    if (!canImport) return;
    const decisions: Record<string, KnowledgeFileDecision> = {};
    for (const rawPath of selectedQaPaths) {
      const fileConflicts = conflicts[rawPath] ?? {};
      const fileImages = images[rawPath] ?? {};
      decisions[rawPath] = {
        conflicts: fileConflicts,
        images: fileImages,
      };
    }
    onConfirm(selectedQaPaths, decisions);
  };

  return (
    <section
      aria-labelledby="qa-upload-review-title"
      className="space-y-4 rounded-xl border border-border bg-surface-raised p-4"
    >
      <div>
        <h3 id="qa-upload-review-title" className="text-base font-semibold text-content">
          匯入前檢查
        </h3>
        <p className="mt-0.5 text-xs text-content-muted">
          確認問答表的題目、答案與分類位置後再匯入。
        </p>
      </div>

      <input {...fileInputProps} data-testid="qa-review-image-input" />

      {uploadError && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-2.5 text-sm text-danger">
          {uploadError}
        </p>
      )}

      {hasConflicts && (
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => setAllConflicts("overwrite")}>
            重複的全部覆蓋
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setAllConflicts("keep")}>
            重複的全部保留原本
          </button>
        </div>
      )}

      <div className="space-y-4">
        {files.map((file, fileIndex) => {
          const displayName = vendor ? `問答表 ${fileIndex + 1}` : file.name;
          const hasErrors = file.preview.errors.length > 0;
          const isChecked = !hasErrors && Boolean(selected[file.rawPath]);

          const newCount = file.preview.questions.filter((q) => q.status === "new").length;
          const sameCount = file.preview.questions.filter((q) => q.status === "same").length;
          const conflictQuestions = file.preview.questions.filter((q) => q.status === "conflict");
          const conflictCount = conflictQuestions.length;

          // 廠商畫面不顯示檔名：以檔名建立的分類改用和分類樹相同的遮蔽名稱。
          const stem = fileNameOf(file.preview.target).replace(/\.[^.]+$/, "");
          const labelOf = (part: string, existing?: QaNode) => existing
            ? categoryLabels?.get(existing.node_id) ?? existing.label
            : vendor && part === stem ? `${displayName}的題目` : part;
          const placementRows = flattenPlacementTree(
            buildPlacementTree(file.preview.questions, nodesTree, labelOf),
          );

          return (
            <article
              key={file.rawPath}
              aria-label={`檢查 ${displayName}`}
              className="space-y-4 rounded-xl border border-border bg-surface p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="flex min-w-0 items-center gap-2 text-sm font-medium text-content">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    disabled={hasErrors}
                    aria-label={`匯入 ${displayName}`}
                    onChange={(event) =>
                      setSelected((prev) => ({
                        ...prev,
                        [file.rawPath]: event.target.checked,
                      }))
                    }
                  />
                  <ImportFileName name={displayName} />
                </label>
                {hasErrors && (
                  <span className="text-xs font-medium text-danger">
                    請改好檔案後重新上傳
                  </span>
                )}
              </div>

              {/* 1. 摘要 */}
              <p className="text-sm text-content">
                新題目 {newCount}、重複（答案相同）{sameCount}、重複（答案不同）{conflictCount}、檔案內重複 {file.preview.duplicate_rows}、格式錯誤 {file.preview.errors.length}
              </p>

              {/* 2. 格式錯誤 */}
              {hasErrors && (
                <div
                  role="alert"
                  className="space-y-1.5 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger"
                >
                  <p className="font-semibold">格式錯誤（請改好檔案後重新上傳）</p>
                  <ul className="list-inside list-disc space-y-1">
                    {file.preview.errors.map((err) => (
                      <li key={err} className="[overflow-wrap:anywhere]">{err}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 3. 答案不同的題目 */}
              {!hasErrors && conflictQuestions.length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-content">答案不同的題目</h4>
                  <div className="space-y-3">
                    {conflictQuestions.map((q) => {
                      const currentChoice = conflicts[file.rawPath]?.[q.question];
                      const radioGroupName = JSON.stringify([file.rawPath, q.question]);
                      return (
                        <div
                          key={q.question}
                          className="space-y-3 rounded-lg border border-border bg-surface-raised p-3"
                        >
                          <p className="text-sm font-semibold text-content [overflow-wrap:anywhere]">{q.question}</p>
                          <AnswerComparison question={q} />

                          <div
                            role="radiogroup"
                            aria-label={`${q.question} 的處理方式`}
                            className="flex flex-wrap gap-x-4 gap-y-2 pt-1"
                          >
                            {CONFLICT_OPTIONS.map((option) => (
                              <label
                                key={option.value}
                                className="flex cursor-pointer items-center gap-1.5 text-sm text-content"
                              >
                                <input
                                  type="radio"
                                  name={radioGroupName}
                                  value={option.value}
                                  checked={currentChoice === option.value}
                                  onChange={() =>
                                    setConflictChoice(file.rawPath, q.question, option.value)
                                  }
                                />
                                <span>{option.label}</span>
                              </label>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* 4. 找不到的圖片 */}
              {file.preview.missing_images.length > 0 && (
                <div className="space-y-2">
                  <div>
                    <h4 className="text-sm font-semibold text-content">找不到的圖片</h4>
                    <p className="mt-0.5 text-xs text-content-muted">
                      沒補傳也可以匯入，那幾題就沒有圖片。
                    </p>
                  </div>
                  <ul className="divide-y divide-border rounded-lg border border-border bg-surface-raised">
                    {file.preview.missing_images.map((missing) => {
                      const rowKey = `${file.rawPath}::${missing.image}`;
                      const replacedId = images[file.rawPath]?.[missing.image];
                      const isUploading = uploadingRowId === rowKey;
                      return (
                        <li
                          key={missing.image}
                          className="flex flex-wrap items-center justify-between gap-3 p-3"
                        >
                          <div className="min-w-0 flex-1 space-y-0.5">
                            <p className="text-sm font-medium text-content [overflow-wrap:anywhere]">{missing.image}</p>
                            <p className="text-xs text-content-muted [overflow-wrap:anywhere]">
                              用到這張圖的題目：{missing.questions.join("、")}
                            </p>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            {replacedId && (
                              <QaImagePreview
                                imageId={replacedId}
                                alt={missing.image}
                                compact
                              />
                            )}
                            <button
                              type="button"
                              className="btn btn-ghost px-2.5 py-1 text-xs"
                              disabled={isUploading}
                              onClick={() => pickImage(rowKey)}
                            >
                              {isUploading ? "上傳中…" : "補傳圖片"}
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}

              {/* 5. 放到哪裡 */}
              <div className="space-y-1.5">
                <h4 className="text-sm font-semibold text-content">放到哪裡</h4>
                {placementRows.length > 0 ? (
                  <ul
                    aria-label={`${displayName} 分類預覽`}
                    className="space-y-1 rounded-lg border border-border bg-surface-raised p-3 text-sm"
                  >
                    {placementRows.map((node) => (
                      <li
                        key={node.pathKey}
                        style={{ paddingLeft: `${node.depth * 1.25}rem` }}
                        className="flex flex-wrap items-center gap-2 text-content"
                      >
                        <span className="min-w-0 font-medium [overflow-wrap:anywhere]">{node.label}</span>
                        {node.isNew && (
                          <span className="chip text-xs text-primary">新</span>
                        )}
                        {node.count > 0 && (
                          <span className="text-xs text-content-muted">
                            {`${node.count} 題`}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-content-muted">
                    這份文件的分類已移除，只更新文件內容，不會放進選單。
                  </p>
                )}
              </div>
            </article>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
        <button
          type="button"
          className="btn btn-ghost"
          onClick={onCancel}
        >
          取消
        </button>
        {missingChoices > 0 && (
          <span id="qa-review-missing-choices" role="status" className="text-sm text-content-muted">
            還有 {missingChoices} 題沒選
          </span>
        )}
        <button
          type="button"
          className="btn btn-primary"
          aria-describedby={missingChoices ? "qa-review-missing-choices" : undefined}
          disabled={!canImport}
          onClick={handleImportClick}
        >
          匯入
        </button>
      </div>
    </section>
  );
}

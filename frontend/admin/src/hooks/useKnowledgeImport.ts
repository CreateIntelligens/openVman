import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
} from "react";

import {
  commitRawKnowledge,
  discardRawPending,
  fetchRawPending,
  getCommitStatus,
  uploadRawKnowledgeDocuments,
  type KnowledgeCommitFileResult,
  type KnowledgeCommitJob,
  type KnowledgeRawPendingFile,
  type KnowledgeUploadEntry,
} from "../api";
import {
  DOCUMENTS_ROOT_PATH,
  DOCUMENTS_SECTION_LABEL,
  fileNameOf,
} from "../components/kb/helpers";
import { errorMessage } from "../utils/errorMessage";
import { currentStorageScope } from "../utils/scopedStorage";
import { formatUploadSize } from "../utils/uploadLimits";

export type ImportItemState =
  | "uploading"
  | "waiting"
  | "processing"
  | "done"
  | "skipped"
  | "failed";

export interface ImportItem {
  id: string;
  /** 畫面上的名稱。拖資料夾進來時保留相對路徑，兩個同名檔才分得出來。 */
  name: string;
  /** 接手別處開始的匯入時不知道大小。 */
  size?: number;
  state: ImportItemState;
  /** 相對 raw/ 的路徑，上傳完才有。 */
  rawPath?: string;
  /** 這批有沒有讓 AI 整理排版。接手別處開始的匯入時不知道，是 undefined。 */
  normalize?: boolean;
  result?: KnowledgeCommitFileResult;
  /** skipped、failed 的白話原因。 */
  message?: string;
  /** 連續的匯入算同一輪，頁首的「匯入中 1/3」才不會跳回 0。 */
  run: number;
}

export interface ImportProgress {
  done: number;
  total: number;
}

export interface ImportTargetOption {
  value: string;
  label: string;
}

/** 要跟 Brain 的 SUPPORTED_SUFFIXES 一致；上傳端點收得更多，但那些匯入時會被拒絕。 */
export const IMPORT_ACCEPT = ".xlsx,.csv,.docx,.pdf,.md,.txt";
export const IMPORT_FORMATS_LABEL = "Excel（.xlsx）、CSV、Word（.docx）、PDF、Markdown（.md）、純文字（.txt）";

const SUPPORTED_SUFFIXES = new Set(IMPORT_ACCEPT.split(","));
// 拖資料夾時作業系統夾帶的檔案，使用者沒有選它們，列出來只是雜訊。
const SYSTEM_FILE_NAMES = new Set(["thumbs.db", "desktop.ini"]);
const QA_FOLDER = `${DOCUMENTS_ROOT_PATH}/qa`;

const DEFAULT_POLL_INTERVAL_MS = 2000;
// 部署時服務會中斷一兩分鐘，撐過去之後看到 job 不見了，才會判定中斷。
const MAX_POLL_FAILURES = 30;

const REASON_MISSING = "找不到這個檔案，可能已經被移除";
const REASON_NO_RESULT = "沒有處理完，可以再試一次";
const REASON_INTERRUPTED = "匯入中斷了，檔案還留著，可以再試一次";
const REASON_CONNECTION = "連不上伺服器，還不確定有沒有匯入成功。請重新整理頁面看看";
const REASON_UPLOAD_LOST = "伺服器沒有收到這個檔案，請再上傳一次";
const REASON_LEFT_DURING_UPLOAD = "上傳途中離開了頁面，檔案沒有傳完，請再上傳一次";
const REASON_LEFT_DURING_IMPORT = "離開頁面時還沒開始匯入，檔案還留著，可以再試一次";

const EMPTY_ITEMS: ImportItem[] = [];
const EMPTY_PENDING: KnowledgeRawPendingFile[] = [];

const IMPORT_ITEM_STATES = new Set<ImportItemState>([
  "uploading",
  "waiting",
  "processing",
  "done",
  "skipped",
  "failed",
]);

export function isImportItemActive(item: Pick<ImportItem, "state">): boolean {
  return item.state === "uploading" || item.state === "waiting" || item.state === "processing";
}

function rawKey(path: string): string {
  return path.replace(/^raw\//, "");
}

function rawUploadTargetFor(targetDir: string): string {
  const relativeDir = targetDir.replace(/^knowledge(\/|$)/, "");
  return relativeDir ? `raw/${relativeDir}` : "raw";
}

function folderLabel(dir: string): string {
  return dir === DOCUMENTS_ROOT_PATH
    ? `${DOCUMENTS_SECTION_LABEL}（最上層）`
    : dir.replace(`${DOCUMENTS_ROOT_PATH}/`, "").split("/").join(" › ");
}

function isSystemFile(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.startsWith(".") || SYSTEM_FILE_NAMES.has(lower);
}

function rejectionReason(file: File, maxFileBytes: number): string | null {
  const dot = file.name.lastIndexOf(".");
  const suffix = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!SUPPORTED_SUFFIXES.has(suffix)) {
    return `這個格式不能匯入，請改用 ${IMPORT_FORMATS_LABEL}`;
  }
  if (file.size > maxFileBytes) {
    return `檔案太大，每個檔案要在 ${formatUploadSize(maxFileBytes)} 以內`;
  }
  return null;
}

/** 進度只會往前走，已經有結果的列不會被之後的輪詢改掉。 */
function withJobProgress(item: ImportItem, job: KnowledgeCommitJob): ImportItem {
  if (!isImportItemActive(item) || !item.rawPath) return item;
  const result = job.results?.[item.rawPath];
  if (result) return { ...item, state: "done", result };
  const reason = job.skip_reasons?.[item.rawPath];
  if (reason) return { ...item, state: "skipped", message: reason };
  switch (job.files?.[item.rawPath]) {
    case "committed":
      return { ...item, state: "done" };
    // 沒附原因的略過不是內容被拒絕，看不出要改什麼，所以當成沒完成、可以再試一次。
    case "skipped":
      return { ...item, state: "failed", message: REASON_NO_RESULT };
    case "normalizing":
      return item.state === "processing" ? item : { ...item, state: "processing" };
    case "pending":
      return item.state === "waiting" ? item : { ...item, state: "waiting" };
    default:
      return item;
  }
}

export function computeImportProgress(items: ImportItem[]): ImportProgress | null {
  if (!items.some(isImportItemActive)) return null;
  const run = Math.max(...items.map((item) => item.run));
  const inRun = items.filter((item) => item.run === run);
  return {
    done: inRun.filter((item) => !isImportItemActive(item)).length,
    total: inRun.length,
  };
}

/** 等待匯入的清單：還列在結果裡、還沒成功的檔案不重複列，已成功的同名檔是新傳的。 */
function visiblePending(
  pending: KnowledgeRawPendingFile[],
  items: ImportItem[],
): KnowledgeRawPendingFile[] {
  const shown = new Set(
    items
      .filter((item) => item.state !== "done" && item.rawPath)
      .map((item) => item.rawPath as string),
  );
  return pending.filter((file) => !shown.has(file.path));
}

/* ── 結果留存 ──
 * 匯入常常要等幾分鐘，使用者會先去別頁。頁面元件一卸載，結果不能跟著不見，
 * 所以放 sessionStorage：同一分頁回來還在，關掉分頁就算了。
 */

function storedItemsKey(projectId: string): string {
  return `kb-import-items:${currentStorageScope()}:${projectId}`;
}

function isStoredItem(value: unknown): value is ImportItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<ImportItem>;
  return typeof item.id === "string"
    && typeof item.name === "string"
    && typeof item.run === "number"
    && IMPORT_ITEM_STATES.has(item.state as ImportItemState);
}

function readStoredItems(projectId: string): ImportItem[] {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(storedItemsKey(projectId)) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isStoredItem) : [];
  } catch {
    return [];
  }
}

function writeStoredItems(projectId: string, items: ImportItem[]): void {
  try {
    if (items.length) {
      sessionStorage.setItem(storedItemsKey(projectId), JSON.stringify(items));
    } else {
      sessionStorage.removeItem(storedItemsKey(projectId));
    }
  } catch {
    // 存不了只是回來時看不到舊結果，不影響匯入本身。
  }
}

/* ── 拖放 ── */

async function collectFileSystemEntries(roots: FileSystemEntry[]): Promise<KnowledgeUploadEntry[]> {
  const out: KnowledgeUploadEntry[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry;
      const file: File = await new Promise((resolve, reject) => fileEntry.file(resolve, reject));
      out.push({ file, relativePath: prefix ? `${prefix}/${file.name}` : file.name });
      return;
    }
    if (entry.isDirectory) {
      const dirEntry = entry as FileSystemDirectoryEntry;
      const reader = dirEntry.createReader();
      const next = prefix ? `${prefix}/${entry.name}` : entry.name;
      // readEntries returns at most 100 per call; loop until empty.
      while (true) {
        const batch: FileSystemEntry[] = await new Promise((resolve, reject) =>
          reader.readEntries(resolve, reject),
        );
        if (!batch.length) break;
        for (const child of batch) {
          await walk(child, next);
        }
      }
    }
  };
  for (const root of roots) {
    await walk(root, "");
  }
  return out;
}

function entriesFromFiles(files: Iterable<File>): KnowledgeUploadEntry[] {
  return Array.from(files, (file) => ({
    file,
    relativePath: file.webkitRelativePath || file.name,
  }));
}

/** dataTransfer 在事件結束後就失效，取項目的部分要在第一個 await 之前做完。 */
function collectDroppedEntries(dataTransfer: DataTransfer): Promise<KnowledgeUploadEntry[]> {
  const items = dataTransfer.items;
  if (items && items.length && typeof items[0].webkitGetAsEntry === "function") {
    const roots = Array.from(items)
      .map((item) => item.webkitGetAsEntry())
      .filter((entry): entry is FileSystemEntry => entry !== null);
    return collectFileSystemEntries(roots);
  }
  return Promise.resolve(entriesFromFiles(dataTransfer.files));
}

function isFileDragEvent(event: DragEvent): boolean {
  return event.dataTransfer?.types?.includes("Files") ?? false;
}

/* ── 匯入工作階段 ──
 * 一個專案一個 session，切換專案或卸載時 cancel。API 都打「目前專案」，所以每個
 * await 之後都要先看 cancelled：不只是不能寫舊專案的狀態，繼續跑還會把舊專案的
 * 路徑送到新專案去。
 */

interface ImportBatch {
  itemIds: Set<string>;
  paths: string[];
  normalize: boolean;
  /** 接手伺服器上已經在跑的匯入，不用再送一次。 */
  runningJob?: KnowledgeCommitJob;
}

interface ImportView {
  projectId: string;
  items: ImportItem[];
  pending: KnowledgeRawPendingFile[];
}

interface SessionOptions {
  projectId: string;
  pollIntervalMs: number;
  onChange: (view: ImportView) => void;
  /** 有檔案匯入成功時呼叫，更新文件清單與快速問答；回傳的 Promise 不能 reject。 */
  onKnowledgeChanged: () => Promise<unknown>;
}

let nextItemNumber = 0;

function newItemId(): string {
  nextItemNumber += 1;
  return `import-${Date.now().toString(36)}-${nextItemNumber}`;
}

function createImportSession({
  projectId,
  pollIntervalMs,
  onChange,
  onKnowledgeChanged,
}: SessionOptions) {
  let cancelled = false;
  let items = readStoredItems(projectId);
  let pending: KnowledgeRawPendingFile[] = [];
  let draining = false;
  let pendingRequest = 0;
  const queue: ImportBatch[] = [];

  const publish = () => {
    if (cancelled) return;
    writeStoredItems(projectId, items);
    onChange({ projectId, items, pending });
  };

  const setItems = (next: ImportItem[]) => {
    items = next;
    publish();
  };

  const nextRun = (): number => {
    const lastRun = items.length ? Math.max(...items.map((item) => item.run)) : 0;
    return items.some(isImportItemActive) ? lastRun : lastRun + 1;
  };

  const sleep = () => new Promise<void>((resolve) => {
    setTimeout(resolve, pollIntervalMs);
  });

  const refreshPending = async () => {
    if (cancelled) return;
    pendingRequest += 1;
    const request = pendingRequest;
    try {
      const response = await fetchRawPending();
      if (cancelled || request !== pendingRequest) return;
      pending = response.files ?? [];
      publish();
    } catch {
      // 這份清單只是提醒，抓不到就維持原樣，不用打斷使用者。
    }
  };

  const refreshKnowledge = async () => {
    if (!cancelled) await onKnowledgeChanged();
  };

  const settleBatch = (batch: ImportBatch, state: "skipped" | "failed", message: string) => {
    setItems(items.map((item) =>
      batch.itemIds.has(item.id) && isImportItemActive(item)
        ? { ...item, state, message }
        : item));
  };

  const finishBatch = async () => {
    await refreshKnowledge();
    await refreshPending();
  };

  const applyJob = (itemIds: ReadonlySet<string>, job: KnowledgeCommitJob) => {
    let changed = false;
    const next = items.map((item) => {
      if (!itemIds.has(item.id)) return item;
      const updated = withJobProgress(item, job);
      if (updated !== item) changed = true;
      return updated;
    });
    if (changed) setItems(next);
  };

  /** 等別人的那一批結束；回傳 false 代表專案已經切走。 */
  const waitForRunningJob = async (
    onUpdate: (job: KnowledgeCommitJob) => void,
  ): Promise<boolean> => {
    let failures = 0;
    while (failures < MAX_POLL_FAILURES) {
      await sleep();
      if (cancelled) return false;
      try {
        const job = await getCommitStatus();
        if (cancelled) return false;
        onUpdate(job);
        if (job.state !== "running") return true;
        failures = 0;
      } catch {
        if (cancelled) return false;
        failures += 1;
      }
    }
    return true;
  };

  const watchJob = async (batch: ImportBatch, firstJob: KnowledgeCommitJob) => {
    const startedAt = firstJob.started_at;
    let job = firstJob;
    let failures = 0;
    let knownResults = 0;
    while (job.state === "running") {
      applyJob(batch.itemIds, job);
      // 做完一個就更新：樹上找不到新分類的話，這一列的「查看」「改名」會沒有反應。
      const resultCount = Object.keys(job.results ?? {}).length;
      if (resultCount > knownResults) void refreshKnowledge();
      knownResults = resultCount;

      await sleep();
      if (cancelled) return;
      let next: KnowledgeCommitJob;
      try {
        next = await getCommitStatus();
      } catch {
        if (cancelled) return;
        failures += 1;
        if (failures < MAX_POLL_FAILURES) continue;
        settleBatch(batch, "failed", REASON_CONNECTION);
        await finishBatch();
        return;
      }
      if (cancelled) return;
      failures = 0;
      // started_at 變了：服務重啟過，或別人接著開了下一批，這批的結果已經拿不到。
      if (next.started_at !== startedAt) {
        settleBatch(batch, "failed", REASON_INTERRUPTED);
        await finishBatch();
        return;
      }
      job = next;
    }
    applyJob(batch.itemIds, job);
    settleBatch(batch, "failed", job.error ?? REASON_NO_RESULT);
    await finishBatch();
  };

  const runBatch = async (batch: ImportBatch) => {
    let job = batch.runningJob ?? null;
    let paths = batch.paths;
    while (!job) {
      let otherJob: KnowledgeCommitJob | undefined;
      try {
        const response = await commitRawKnowledge({ paths, normalize: batch.normalize });
        if (cancelled) return;
        if (response.status === "nothing_to_commit") {
          settleBatch(batch, "skipped", REASON_MISSING);
          await finishBatch();
          return;
        }
        if (response.status === "started") {
          job = response.job ?? (await getCommitStatus());
          if (cancelled) return;
          break;
        }
        otherJob = response.job;
      } catch (error) {
        if (cancelled) return;
        settleBatch(batch, "failed", errorMessage(error, REASON_NO_RESULT));
        await finishBatch();
        return;
      }

      // already_running 不會排隊，要等那批結束再送一次，否則這批永遠不會開始。
      // 例外是還排在那批裡的同名檔（另一個分頁或另一位管理員同時傳）：輪到時讀到的就是
      // 這邊傳的內容，它的結果就是這邊的結果，再送一次反而會說找不到檔案。
      const queuedThere = new Set(paths.filter((path) => otherJob?.files?.[path] === "pending"));
      const followedIds = new Set(items
        .filter((item) => batch.itemIds.has(item.id) && queuedThere.has(item.rawPath as string))
        .map((item) => item.id));
      if (!(await waitForRunningJob((running) => applyJob(followedIds, running)))) return;

      const unfinished = new Set(items
        .filter((item) => batch.itemIds.has(item.id) && isImportItemActive(item))
        .map((item) => item.rawPath));
      paths = paths.filter((path) => unfinished.has(path));
      if (!paths.length) {
        await finishBatch();
        return;
      }
    }
    await watchJob(batch, job);
  };

  const drain = async () => {
    if (draining) return;
    draining = true;
    try {
      while (!cancelled && queue.length) {
        const batch = queue[0];
        try {
          await runBatch(batch);
        } catch (error) {
          // 不能讓一批出錯就卡住後面每一批，這些列也不能永遠轉圈。
          settleBatch(batch, "failed", errorMessage(error, REASON_NO_RESULT));
        }
        queue.shift();
      }
    } finally {
      draining = false;
    }
  };

  const enqueue = (batch: ImportBatch) => {
    queue.push(batch);
    void drain();
  };

  /**
   * 同一個檔案又傳一次、而舊的那列還在排隊：後端輪到時讀到的就是新版，下一批再送會
   * 說找不到檔案。所以新列直接接手舊列在那一批的位置。
   */
  const takeOverWaitingRow = (row: ImportItem): boolean => {
    const older = items.find((item) =>
      item.id !== row.id && item.state === "waiting" && item.rawPath === row.rawPath);
    const batch = older && queue.find((candidate) => candidate.itemIds.has(older.id));
    if (!older || !batch) return false;
    batch.itemIds.delete(older.id);
    batch.itemIds.add(row.id);
    items = items.filter((item) => item.id !== older.id);
    return true;
  };

  const uploadAndImport = async (
    entries: KnowledgeUploadEntry[],
    options: { targetDir: string; normalize: boolean; maxFileBytes: number },
  ) => {
    const run = nextRun();
    const accepted: { id: string; entry: KnowledgeUploadEntry }[] = [];
    const rows: ImportItem[] = [];
    for (const entry of entries) {
      if (isSystemFile(entry.file.name)) continue;
      const row: ImportItem = {
        id: newItemId(),
        name: entry.relativePath || entry.file.name,
        size: entry.file.size,
        state: "uploading",
        normalize: options.normalize,
        run,
      };
      const reason = rejectionReason(entry.file, options.maxFileBytes);
      if (reason) {
        rows.push({ ...row, state: "skipped", message: reason });
      } else {
        rows.push(row);
        accepted.push({ id: row.id, entry });
      }
    }
    if (!rows.length) return;
    setItems([...items, ...rows]);
    if (!accepted.length) return;

    const acceptedIds = new Set(accepted.map(({ id }) => id));
    let paths: (string | undefined)[];
    try {
      const response = await uploadRawKnowledgeDocuments(
        accepted.map(({ entry }) => entry),
        rawUploadTargetFor(options.targetDir),
      );
      if (cancelled) return;
      // 後端照送出的順序逐檔存，回傳順序就是送出的順序。
      paths = accepted.map((_, index) => {
        const path = response.files?.[index]?.path;
        return path ? rawKey(path) : undefined;
      });
    } catch (error) {
      if (cancelled) return;
      setItems(items.map((item) =>
        acceptedIds.has(item.id)
          ? { ...item, state: "failed", message: errorMessage(error, REASON_UPLOAD_LOST) }
          : item));
      // 一批裡前面的檔案可能已經存好了，要列得出來才移得掉。
      void refreshPending();
      return;
    }

    const pathById = new Map(accepted.map(({ id }, index) => [id, paths[index]]));
    items = items.map((item) => {
      if (!acceptedIds.has(item.id)) return item;
      const rawPath = pathById.get(item.id);
      return rawPath
        ? { ...item, state: "waiting", rawPath }
        : { ...item, state: "failed", message: REASON_UPLOAD_LOST };
    });

    const batchPaths = new Set<string>();
    const batchIds = new Set<string>();
    for (const item of items) {
      if (!acceptedIds.has(item.id) || item.state !== "waiting") continue;
      if (takeOverWaitingRow(item)) continue;
      batchIds.add(item.id);
      batchPaths.add(item.rawPath as string);
    }
    publish();
    if (batchIds.size) {
      enqueue({ itemIds: batchIds, paths: [...batchPaths], normalize: options.normalize });
    }
  };

  const importExisting = (files: KnowledgeRawPendingFile[], normalize: boolean) => {
    if (!files.length) return;
    const run = nextRun();
    const rows = files.map<ImportItem>((file) => ({
      id: newItemId(),
      name: file.path,
      size: file.size,
      state: "waiting",
      rawPath: file.path,
      normalize,
      run,
    }));
    setItems([...items, ...rows]);
    enqueue({
      itemIds: new Set(rows.map((row) => row.id)),
      paths: rows.map((row) => row.rawPath as string),
      normalize,
    });
  };

  const retry = (itemId: string) => {
    const target = items.find((item) => item.id === itemId);
    if (!target?.rawPath || isImportItemActive(target)) return;
    const run = nextRun();
    setItems(items.map((item) =>
      item.id === itemId
        ? { ...item, state: "waiting", message: undefined, result: undefined, run }
        : item));
    enqueue({
      itemIds: new Set([itemId]),
      paths: [target.rawPath],
      // 不知道原本怎麼匯入的，就照原樣：不讓 AI 改到可能已經整理好的文件。
      normalize: target.normalize ?? false,
    });
  };

  const clearFinished = () => {
    setItems(items.filter(isImportItemActive));
    void refreshPending();
  };

  /** 回來時收尾上次還沒結束的列；伺服器上如果有匯入在跑，也接手顯示。 */
  const reconcile = async () => {
    // 只動上次留下來的列：查詢途中使用者可能已經又拖了新的檔案進來。
    const leftoverIds = new Set(items.filter(isImportItemActive).map((item) => item.id));
    let job: KnowledgeCommitJob | null = null;
    try {
      job = await getCommitStatus();
    } catch {
      job = null;
    }
    if (cancelled) return;

    const leftBehind = (item: ImportItem): ImportItem => ({
      ...item,
      state: "failed",
      message: item.rawPath ? REASON_LEFT_DURING_IMPORT : REASON_LEFT_DURING_UPLOAD,
    });

    if (job?.state === "running" && !draining) {
      const running = job;
      const paths = Object.keys(running.files ?? {});
      const run = nextRun();
      const tracked = paths.map<ImportItem>((path) => withJobProgress(
        items.find((item) => leftoverIds.has(item.id) && item.rawPath === path) ?? {
          id: newItemId(),
          name: path,
          state: "waiting",
          rawPath: path,
          run,
        },
        running,
      ));
      const trackedById = new Map(tracked.map((row) => [row.id, row]));
      const known = new Set(items.map((item) => item.id));
      setItems([
        ...items.map((item) =>
          trackedById.get(item.id) ?? (leftoverIds.has(item.id) ? leftBehind(item) : item)),
        ...tracked.filter((row) => !known.has(row.id)),
      ]);
      enqueue({
        itemIds: new Set(trackedById.keys()),
        paths,
        normalize: false,
        runningJob: running,
      });
      return;
    }

    if (!leftoverIds.size) return;
    const finished = job?.state === "done" || job?.state === "failed" ? job : null;
    const settled = items.map((item) => {
      if (!leftoverIds.has(item.id)) return item;
      const updated = finished ? withJobProgress(item, finished) : item;
      return isImportItemActive(updated) ? leftBehind(updated) : updated;
    });
    const anyImported = settled.some((item) => leftoverIds.has(item.id) && item.state === "done");
    setItems(settled);
    if (anyImported) void refreshKnowledge();
  };

  const start = () => {
    publish();
    void refreshPending();
    void reconcile();
  };

  return {
    start,
    cancel: () => {
      cancelled = true;
    },
    uploadAndImport,
    importExisting,
    retry,
    clearFinished,
    refreshPending,
    isCancelled: () => cancelled,
    getVisiblePending: () => visiblePending(pending, items),
  };
}

type ImportSession = ReturnType<typeof createImportSession>;

interface UseKnowledgeImportOptions {
  projectId: string;
  /** 現在所在的資料夾，「放到哪個資料夾」的預設值。 */
  currentDir: string;
  /** 伺服器回報的資料夾，例如 knowledge/gear；不含最上層。 */
  directories: string[];
  maxFileBytes: number;
  loadDocuments: () => Promise<unknown>;
  fetchQaTree: () => Promise<unknown>;
  /** 檔案拖進來並開始匯入時呼叫，讓頁面切到結果。 */
  onDropStarted?: () => void;
  onError: (message: string) => void;
  pollIntervalMs?: number;
}

export function useKnowledgeImport({
  projectId,
  currentDir,
  directories,
  maxFileBytes,
  loadDocuments,
  fetchQaTree,
  onDropStarted,
  onError,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: UseKnowledgeImportOptions) {
  const [view, setView] = useState<ImportView>({ projectId, items: [], pending: [] });
  // 預設直接切段放進知識庫；AI 整理是使用者要求才做，整理本身會改動內容。
  const [skipNormalize, setSkipNormalize] = useState(true);
  const [targetChoice, setTargetChoice] = useState<{ dir: string; currentDir: string } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const dragCounterRef = useRef(0);
  const sessionRef = useRef<ImportSession | null>(null);

  // session 活得比一次 render 久，要拿到最新的 callback。
  const latest = useRef({ loadDocuments, fetchQaTree, onDropStarted, onError });
  latest.current = { loadDocuments, fetchQaTree, onDropStarted, onError };

  useEffect(() => {
    const session = createImportSession({
      projectId,
      pollIntervalMs,
      onChange: setView,
      onKnowledgeChanged: () =>
        Promise.allSettled([latest.current.loadDocuments(), latest.current.fetchQaTree()]),
    });
    sessionRef.current = session;
    setSkipNormalize(true);
    setTargetChoice(null);
    session.start();
    return () => {
      session.cancel();
      if (sessionRef.current === session) sessionRef.current = null;
    };
  }, [pollIntervalMs, projectId]);

  // 切換專案的那一次 render，session 還是舊的，不能把舊專案的清單畫出來。
  const items = view.projectId === projectId ? view.items : EMPTY_ITEMS;
  const pending = view.projectId === projectId ? view.pending : EMPTY_PENDING;

  const targetOptions = useMemo<ImportTargetOption[]>(() => {
    const folders = directories.filter((dir) =>
      dir.startsWith(`${DOCUMENTS_ROOT_PATH}/`)
      // 問答表一律存進這裡，它不是給人放文件的資料夾。
      && dir !== QA_FOLDER
      && !dir.startsWith(`${QA_FOLDER}/`));
    return [DOCUMENTS_ROOT_PATH, ...folders].map((dir) => ({ value: dir, label: folderLabel(dir) }));
  }, [directories]);

  // 使用者挑過的資料夾只在「目前資料夾」沒變時有效；點了樹上別的資料夾就跟著走。
  const chosenDir = targetChoice?.currentDir === currentDir ? targetChoice.dir : currentDir;
  const targetDir = targetOptions.some((option) => option.value === chosenDir)
    ? chosenDir
    : DOCUMENTS_ROOT_PATH;
  const targetLabel = folderLabel(targetDir);

  const setTargetDir = useCallback((dir: string) => {
    setTargetChoice({ dir, currentDir });
  }, [currentDir]);

  // AI 整理只用在選了它的這一批：下一批多半是另一種檔案，留著的話內容會被改動。
  const startEntries = useCallback((entries: KnowledgeUploadEntry[]) => {
    void sessionRef.current?.uploadAndImport(entries, {
      targetDir,
      normalize: !skipNormalize,
      maxFileBytes,
    });
    setSkipNormalize(true);
  }, [maxFileBytes, skipNormalize, targetDir]);

  const startFiles = useCallback((files: Iterable<File>) => {
    startEntries(entriesFromFiles(files));
  }, [startEntries]);

  const importPending = useCallback(() => {
    const session = sessionRef.current;
    session?.importExisting(session.getVisiblePending(), !skipNormalize);
    setSkipNormalize(true);
  }, [skipNormalize]);

  const retryItem = useCallback((itemId: string) => {
    sessionRef.current?.retry(itemId);
  }, []);

  const clearResults = useCallback(() => {
    sessionRef.current?.clearFinished();
  }, []);

  const discardPending = useCallback(async (path: string) => {
    const session = sessionRef.current;
    if (!session) return;
    try {
      await discardRawPending(path);
    } catch (error) {
      if (!session.isCancelled()) {
        latest.current.onError(errorMessage(error, `移除 ${fileNameOf(path)} 失敗，請再試一次`));
      }
    }
    await session.refreshPending();
  }, []);

  const handleDragEnter = useCallback((event: DragEvent) => {
    if (!isFileDragEvent(event)) return;
    event.preventDefault();
    dragCounterRef.current += 1;
    if (dragCounterRef.current === 1) setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((event: DragEvent) => {
    if (!isFileDragEvent(event)) return;
    event.preventDefault();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) setDragOver(false);
  }, []);

  const handleDrop = useCallback(async (event: DragEvent) => {
    if (!isFileDragEvent(event)) return;
    event.preventDefault();
    dragCounterRef.current = 0;
    setDragOver(false);
    const session = sessionRef.current;
    let entries: KnowledgeUploadEntry[];
    try {
      entries = await collectDroppedEntries(event.dataTransfer);
    } catch {
      latest.current.onError("讀不到拖進來的檔案，請改用「選擇檔案」試試");
      return;
    }
    if (!session || session.isCancelled()) return;
    if (!entries.length) {
      latest.current.onError("這裡面沒有檔案可以匯入");
      return;
    }
    latest.current.onDropStarted?.();
    startEntries(entries);
  }, [startEntries]);

  const progress = useMemo(() => computeImportProgress(items), [items]);
  const pendingFiles = useMemo(() => visiblePending(pending, items), [items, pending]);

  return {
    items,
    progress,
    pendingFiles,
    targetDir,
    targetLabel,
    targetOptions,
    setTargetDir,
    skipNormalize,
    setSkipNormalize,
    startFiles,
    importPending,
    retryItem,
    clearResults,
    discardPending,
    dragOver,
    handleDragEnter,
    handleDragLeave,
    handleDrop,
  };
}

export type KnowledgeImport = ReturnType<typeof useKnowledgeImport>;

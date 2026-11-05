import { validateUploadFiles } from "../utils/uploadLimits";

import {
  apiUrl,
  del,
  fetchJson,
  get,
  getActiveProjectId,
  knowledgePath,
  patch,
  post,
  projectUrl,
  put,
} from "./common";

export interface KnowledgeDocumentSummary {
  path: string;
  title: string;
  category: string;
  extension: string;
  size: number;
  updated_at: string;
  is_core: boolean;
  is_indexable: boolean;
  is_indexed: boolean;
  preview: string;
  source_type: "upload" | "web" | "manual" | "qa";
  source_url: string | null;
  enabled: boolean;
  created_at: string;
  // 知識庫依語言分流：使用者用哪種語言問，同語言的文件優先（不夠再用其他語言補）。
  language?: KnowledgeLanguage | null;
  language_source?: "auto" | "manual" | null;
  // source_type === "qa" 且被任一問答樹節點掛載時為 true
  qa_attached?: boolean;
  has_original_backup?: boolean;
}

// nan＝台語；專案有台語文件才會在 Live 多聽一次判斷台語。
export type KnowledgeLanguage = "zh" | "en" | "es" | "nan" | "ja" | "ko";

export interface KnowledgeDocument extends KnowledgeDocumentSummary {
  content: string;
  /** 存檔時送回；載入後檔案被改過，存檔會被拒絕，不會蓋掉別處剛存的內容。 */
  content_hash?: string;
}

export interface KnowledgeDocumentsResponse {
  documents: KnowledgeDocumentSummary[];
  document_count: number;
  directories?: string[];
}

export interface KnowledgeUploadResponse {
  status: string;
  files: KnowledgeDocumentSummary[];
}

export interface KnowledgeReindexResponse {
  status: string;
  document_count: number;
  chunk_count: number;
  workspace_root: string;
}

export interface CrawlIngestResponse {
  status: string;
  title: string;
  source_url: string;
  path: string;
  size: number;
}

export interface KnowledgeDocumentMetaResponse {
  status: string;
  path: string;
  enabled: boolean;
  source_type: "upload" | "web" | "manual" | "qa";
  source_url: string | null;
  language?: KnowledgeLanguage | null;
  language_source?: "auto" | "manual" | null;
}

export interface KnowledgeQaEntry {
  path: string;
  question: string;
  answer: string;
}

export interface KnowledgeQaEntriesResponse {
  entries: KnowledgeQaEntry[];
  count: number;
}

export function fetchKnowledgeQaEntries() {
  return get<KnowledgeQaEntriesResponse>(knowledgePath("/qa"));
}

export interface KnowledgeNoteResponse {
  status: string;
  path: string;
  size: number;
  // QA 格式筆記建立時，後端會自動建立問答樹節點並回傳其 id
  document: KnowledgeDocumentSummary & { qa_node_id?: string };
}

export async function fetchKnowledgeDocuments() {
  return get<KnowledgeDocumentsResponse>(knowledgePath("/documents"));
}

export async function fetchKnowledgeBaseDocuments() {
  return get<KnowledgeDocumentsResponse>(knowledgePath("/base/documents"));
}

export async function fetchKnowledgeDocument(path: string) {
  return get<KnowledgeDocument>(knowledgePath("/document"), { path });
}

export function saveKnowledgeDocument(path: string, content: string, baseHash?: string) {
  return put<{ status: string; document: KnowledgeDocumentSummary }>(
    knowledgePath("/document"),
    { path, content, project_id: getActiveProjectId(), ...(baseHash ? { base_hash: baseHash } : {}) },
  );
}

export async function deleteKnowledgeDocument(path: string) {
  return del<{ status: string }>(knowledgePath("/document"), { path });
}

export function createKnowledgeDirectory(dirPath: string) {
  return post<{ status: string; path: string }>(knowledgePath("/directory"), {
    project_id: getActiveProjectId(),
    path: dirPath,
    content: "",
  });
}

export async function deleteKnowledgeDirectory(dirPath: string) {
  return del<{ status: string; path: string }>(
    knowledgePath("/directory"),
    { path: dirPath },
  );
}

export function moveKnowledgeDocument(sourcePath: string, targetPath: string) {
  return post<{ status: string; document: KnowledgeDocumentSummary }>(
    knowledgePath("/move"),
    { source_path: sourcePath, target_path: targetPath, project_id: getActiveProjectId() },
  );
}

export type KnowledgeUploadEntry = { file: File; relativePath: string };

async function validateKnowledgeUpload(entries: KnowledgeUploadEntry[]) {
  const limits = await fetchJson<{ document_max_upload_bytes: number }>(
    apiUrl("/uploads/limits"),
  );
  const error = validateUploadFiles(
    entries.map(({ file }) => file),
    limits.document_max_upload_bytes,
  );
  if (error) throw new Error(error);
}

export async function uploadKnowledgeDocuments(
  entries: KnowledgeUploadEntry[],
  targetDir = "",
) {
  const formData = new FormData();
  entries.forEach(({ file, relativePath }) => {
    formData.append("files", file);
    formData.append("relative_paths", relativePath || file.name);
  });
  formData.append("target_dir", targetDir);
  formData.append("project_id", getActiveProjectId());

  await validateKnowledgeUpload(entries);
  return fetchJson<KnowledgeUploadResponse>(apiUrl(knowledgePath("/upload")), {
    method: "POST",
    body: formData,
  });
}

export async function uploadRawKnowledgeDocuments(
  entries: KnowledgeUploadEntry[],
  targetDir = "raw",
) {
  const formData = new FormData();
  entries.forEach(({ file, relativePath }) => {
    formData.append("files", file);
    formData.append("relative_paths", relativePath || file.name);
  });
  formData.append("target_dir", targetDir);
  formData.append("project_id", getActiveProjectId());

  await validateKnowledgeUpload(entries);
  return fetchJson<KnowledgeUploadResponse>(apiUrl(knowledgePath("/raw/upload")), {
    method: "POST",
    body: formData,
  });
}

export function reindexKnowledge() {
  return post<KnowledgeReindexResponse>(knowledgePath("/reindex"), {
    project_id: getActiveProjectId(),
  });
}

export type KnowledgeCommitFileState =
  | "pending"
  | "normalizing"
  | "committed"
  | "skipped";

/** 一個檔案匯入後的結果。沒有上層的分類不會帶 qa_parent_label。 */
export interface KnowledgeCommitFileResult {
  target: string;
  kind: "qa" | "document";
  language?: KnowledgeLanguage | null;
  updated: boolean;
  qa_node_id?: string;
  qa_node_label?: string;
  qa_parent_label?: string;
  question_count?: number;
}

export interface KnowledgeCommitJob {
  state: "idle" | "running" | "done" | "failed";
  started_at: string | null;
  finished_at: string | null;
  // files、results、skip_reasons 的鍵都相對 raw/，不帶 raw/ 前綴。
  files: Record<string, KnowledgeCommitFileState>;
  committed: string[];
  skipped: string[];
  results: Record<string, KnowledgeCommitFileResult>;
  skip_reasons: Record<string, string>;
  error: string | null;
}

export interface KnowledgeCommitResponse {
  status: "started" | "nothing_to_commit" | "already_running";
  project_id: string;
  committed?: string[];
  skipped?: string[];
  job?: KnowledgeCommitJob;
}

export interface KnowledgeCommitOptions {
  /** 只處理這些檔案（相對 raw/）；不給就是全部。 */
  paths?: string[];
  /** false 時略過 AI 整理；不給就是要整理。 */
  normalize?: boolean;
}

/** Promote staged raw/ files into the knowledge base as a background job. */
export function commitRawKnowledge(options: KnowledgeCommitOptions = {}) {
  return post<KnowledgeCommitResponse>(knowledgePath("/raw/commit"), {
    project_id: getActiveProjectId(),
    ...options,
  });
}

/** Poll per-file progress of the background commit job. */
export function getCommitStatus() {
  return get<KnowledgeCommitJob>(knowledgePath("/raw/commit/status"), {
    project_id: getActiveProjectId(),
  });
}

export interface KnowledgeRawPendingFile {
  /** 相對 raw/，不帶 raw/ 前綴。 */
  path: string;
  size: number;
  updated_at: string;
}

/** 之前上傳、還沒匯入的檔案；正在匯入的不算。 */
export function fetchRawPending() {
  return get<{ files: KnowledgeRawPendingFile[] }>(knowledgePath("/raw/pending"));
}

export function discardRawPending(path: string) {
  return del<{ status: string }>(knowledgePath("/raw/pending"), { path });
}

export interface KnowledgeRenormalizeResponse {
  status: string;
  project_id: string;
  document: { path: string; backup_path?: string; [k: string]: unknown };
  graph?: string;
}

/** Re-run LLM normalization over an existing knowledge document, in place. */
export function renormalizeKnowledgeDocument(path: string) {
  return post<KnowledgeRenormalizeResponse>(knowledgePath("/renormalize"), {
    path,
    project_id: getActiveProjectId(),
  });
}

export interface KnowledgeNormalizationPreviewResponse {
  status: string;
  project_id: string;
  path: string;
  title: string;
  extension: string;
  content: string;
  size: number;
  preview: string;
}

export function previewRenormalizedKnowledgeDocument(path: string) {
  return post<KnowledgeNormalizationPreviewResponse>(knowledgePath("/renormalize/preview"), {
    path,
    project_id: getActiveProjectId(),
  });
}

export function applyRenormalizedKnowledgeDocument(path: string, content: string) {
  return post<KnowledgeRenormalizeResponse>(knowledgePath("/renormalize/apply"), {
    path,
    content,
    project_id: getActiveProjectId(),
  });
}

interface FetchPageResponse {
  status: string;
  title: string;
  source_url: string;
  content: string;
  language?: string;
  video_id?: string;
}

function sanitizeFilename(name: string): string {
  const cleaned = name.replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim();
  return cleaned.length > 0 ? cleaned.slice(0, 120) : "untitled";
}

export async function crawlUrl(url: string): Promise<CrawlIngestResponse> {
  const fetched = await post<FetchPageResponse>(knowledgePath("/fetch"), {
    url,
    project_id: getActiveProjectId(),
  });

  const title = fetched.title || url;
  const filename = `${sanitizeFilename(title)}.md`;
  const file = new File([`# ${title}\n\n${fetched.content}`], filename, { type: "text/markdown" });

  const uploaded = await uploadKnowledgeDocuments([{ file, relativePath: filename }]);
  const summary = uploaded.files[0];
  if (!summary) throw new Error("匯入成功但未取得文件資訊");

  // metadata 更新失敗不阻擋匯入流程
  updateKnowledgeDocumentMeta(summary.path, {
    source_type: "web",
    source_url: fetched.source_url || url,
  }).catch(() => {});

  return {
    status: uploaded.status,
    title: summary.title || title,
    source_url: fetched.source_url || url,
    path: summary.path,
    size: summary.size,
  };
}

export function updateKnowledgeDocumentMeta(
  path: string,
  metadata: {
    enabled?: boolean;
    source_type?: "upload" | "web" | "manual" | "qa";
    source_url?: string | null;
    // auto：取消手動指定，改回依內容判斷。
    language?: KnowledgeLanguage | "auto";
  },
) {
  return patch<KnowledgeDocumentMetaResponse>(
    knowledgePath("/document/meta"),
    { path, project_id: getActiveProjectId(), ...metadata },
  );
}

export interface SpeechRates {
  chars_per_second: number;
  words_per_second: number;
}

export interface KnowledgeSettings {
  // zh 一定在；只有 zh 時不分流。nan（台語）勾了 Live 才會另外聽使用者是不是講台語。
  language_routes: KnowledgeLanguage[];
  // 回答要在幾秒內念完，0 是不限制；不帶就保留原本的設定。
  reply_seconds?: number;
  // Brain 換算「幾秒＝幾個字」用的語速，只讀。
  speech_rates?: SpeechRates;
}

export function fetchKnowledgeSettings() {
  return get<KnowledgeSettings>(knowledgePath("/settings"));
}

/** 指定專案的知識庫設定，不看目前選中的專案（權限圖譜一次讀所有專案）。 */
export function fetchProjectKnowledgeSettings(projectId: string) {
  return get<KnowledgeSettings>(knowledgePath("/settings"), { project_id: projectId });
}

export function saveKnowledgeSettings(settings: KnowledgeSettings) {
  return put<KnowledgeSettings>(knowledgePath("/settings"), {
    project_id: getActiveProjectId(),
    ...settings,
  });
}

export type KnowledgeNoteFormat = "text" | "qa";

export function createKnowledgeNote(
  title: string,
  content: string,
  targetDir = "",
  noteFormat: KnowledgeNoteFormat = "text",
) {
  return post<KnowledgeNoteResponse>(knowledgePath("/note"), {
    title,
    content,
    project_id: getActiveProjectId(),
    target_dir: targetDir,
    note_format: noteFormat,
  });
}

export interface GraphStatus {
  state: "absent" | "building" | "ready" | "failed";
  project_id: string;
  started_at?: string;
  finished_at?: string;
  nodes?: number;
  edges?: number;
  communities?: number;
  error?: string;
  stale?: boolean;
}

export interface GraphSummary {
  project_id: string;
  built_at: string;
  nodes: number;
  edges: number;
  communities: number;
  god_nodes: string[];
  surprising_bridges: number;
  ast_nodes: number;
  semantic_nodes: number;
}

export function fetchGraphStatus() {
  return get<GraphStatus>(knowledgePath("/graph/status"));
}

export function fetchGraphSummary() {
  return get<GraphSummary>(knowledgePath("/graph/summary"));
}

export function rebuildGraph() {
  return post<{ status: string; project_id: string }>(knowledgePath("/graph/rebuild"), {
    project_id: getActiveProjectId(),
  });
}

export function graphHtmlUrl(): string {
  return projectUrl(knowledgePath("/graph/html"));
}

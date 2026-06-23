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
  source_type: "upload" | "web" | "manual";
  source_url: string | null;
  enabled: boolean;
  created_at: string;
}

export interface KnowledgeDocument extends KnowledgeDocumentSummary {
  content: string;
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
  source_type: "upload" | "web" | "manual";
  source_url: string | null;
}

export interface KnowledgeNoteResponse {
  status: string;
  path: string;
  size: number;
  document: KnowledgeDocumentSummary;
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

export function saveKnowledgeDocument(path: string, content: string) {
  return put<{ status: string; document: KnowledgeDocumentSummary }>(
    knowledgePath("/document"),
    { path, content, project_id: getActiveProjectId() },
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

  return fetchJson<KnowledgeUploadResponse>(apiUrl(knowledgePath("/upload")), {
    method: "POST",
    body: formData,
  });
}

export function reindexKnowledge() {
  return post<KnowledgeReindexResponse>(knowledgePath("/reindex"), {
    project_id: getActiveProjectId(),
  });
}

export interface KnowledgeCommitResponse {
  status: string;
  project_id: string;
  committed?: string[];
  skipped?: string[];
  graph?: string;
}

/** Promote staged raw/ files into the knowledge base, then reindex + rebuild graph. */
export function commitRawKnowledge() {
  return post<KnowledgeCommitResponse>(knowledgePath("/raw/commit"), {
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
    source_type?: "upload" | "web" | "manual";
    source_url?: string | null;
  },
) {
  return patch<KnowledgeDocumentMetaResponse>(
    knowledgePath("/document/meta"),
    { path, project_id: getActiveProjectId(), ...metadata },
  );
}

export function createKnowledgeNote(title: string, content: string) {
  return post<KnowledgeNoteResponse>(knowledgePath("/note"), {
    title,
    content,
    project_id: getActiveProjectId(),
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

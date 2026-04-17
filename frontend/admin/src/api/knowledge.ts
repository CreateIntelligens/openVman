import { fetchJson, apiUrl, projectUrl, post, jsonRequest, knowledgePath, getActiveProjectId } from "./common";

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
  return fetchJson<KnowledgeDocumentsResponse>(projectUrl(knowledgePath("/documents")));
}

export async function fetchKnowledgeBaseDocuments() {
  return fetchJson<KnowledgeDocumentsResponse>(projectUrl(knowledgePath("/base/documents")));
}

export async function fetchKnowledgeDocument(path: string) {
  return fetchJson<KnowledgeDocument>(projectUrl(knowledgePath("/document"), { path }));
}

export function saveKnowledgeDocument(path: string, content: string) {
  return jsonRequest<{ status: string; document: KnowledgeDocumentSummary }>(
    "PUT",
    knowledgePath("/document"),
    { path, content, project_id: getActiveProjectId() },
  );
}

export async function deleteKnowledgeDocument(path: string) {
  return fetchJson<{ status: string }>(projectUrl(knowledgePath("/document"), { path }), {
    method: "DELETE",
  });
}

export function createKnowledgeDirectory(dirPath: string) {
  return post<{ status: string; path: string }>(knowledgePath("/directory"), {
    project_id: getActiveProjectId(),
    path: dirPath,
    content: "",
  });
}

export async function deleteKnowledgeDirectory(dirPath: string) {
  return fetchJson<{ status: string; path: string }>(
    projectUrl(knowledgePath("/directory"), { path: dirPath }),
    {
      method: "DELETE",
    },
  );
}

export function moveKnowledgeDocument(sourcePath: string, targetPath: string) {
  return post<{ status: string; document: KnowledgeDocumentSummary }>(
    knowledgePath("/move"),
    { source_path: sourcePath, target_path: targetPath, project_id: getActiveProjectId() },
  );
}

export async function uploadKnowledgeDocuments(files: File[], targetDir = "") {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
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

export function crawlUrl(url: string) {
  return post<CrawlIngestResponse>(knowledgePath("/crawl"), {
    url,
    project_id: getActiveProjectId(),
  });
}

export function updateKnowledgeDocumentMeta(
  path: string,
  metadata: {
    enabled?: boolean;
    source_type?: "upload" | "web" | "manual";
    source_url?: string | null;
  },
) {
  return jsonRequest<KnowledgeDocumentMetaResponse>(
    "PATCH",
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
  return fetchJson<GraphStatus>(projectUrl(knowledgePath("/graph/status")));
}

export function fetchGraphSummary() {
  return fetchJson<GraphSummary>(projectUrl(knowledgePath("/graph/summary")));
}

export function rebuildGraph() {
  return post<{ status: string; project_id: string }>(knowledgePath("/graph/rebuild"), {
    project_id: getActiveProjectId(),
  });
}

export function graphHtmlUrl(): string {
  return projectUrl(knowledgePath("/graph/html"));
}

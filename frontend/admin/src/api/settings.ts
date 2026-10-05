import { apiFetch, apiUrl, parseErrorMessage } from "./common";

// apiUrl 會自己補上 /api/v1，這裡再寫一次會變成 /api/v1/api/v1/... 然後 404。
const PREVIEW_PATH = "/asr/preview";

export interface AsrPreview {
  text: string;
  /** 實際辨識的引擎；指定的那家掛掉時會是備援。 */
  provider: string;
  /** 後端量到的轉寫耗時，不含上傳與轉檔。 */
  elapsed_seconds?: number;
  /** 聽出是台語時是 "nan"；其他情況 null。 */
  language?: string | null;
  /** 開台語分流時才有：判斷結果（語言代碼、timeout、failed）與耗時。 */
  language_check?: { result: string; ms: number } | null;
  /** 這次實際套用的語言分流。 */
  language_routes?: string[];
  /** 這次實際送給引擎的詞表；空字串表示沒套用。 */
  glossary?: string;
}

export interface AsrPreviewContext {
  /** 帶了專案就跟正式對話一樣套專案詞表與語言分流。 */
  projectId?: string;
  /** 逗號分隔的分流代碼，例如 "zh,nan"；不帶就用專案設定。 */
  languageRoutes?: string;
}

/**
 * 用指定的引擎轉寫一段錄音，讓操作者當場比較各家。只影響這一次，不改任何人
 * 的設定；provider 留空就用部署預設。
 */
export async function previewAsr(
  clip: Blob,
  filename?: string,
  provider = "",
  context: AsrPreviewContext = {},
): Promise<AsrPreview> {
  const form = new FormData();
  // 副檔名決定後端暫存檔的 suffix，進而決定 ffmpeg 怎麼解這個檔：上傳的
  // mp3 若冠上 .webm，轉檔就會失敗。錄音沒有檔名，那才是 webm。
  form.append("file", clip, filename || "preview.webm");
  if (provider) form.append("provider", provider);
  if (context.projectId) form.append("project_id", context.projectId);
  if (context.languageRoutes) form.append("language_routes", context.languageRoutes);
  const res = await apiFetch(apiUrl(PREVIEW_PATH), {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await parseErrorMessage(res));
  return (await res.json()) as AsrPreview;
}

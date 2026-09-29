import { apiFetch, apiUrl, parseErrorMessage } from "./common";

// apiUrl 會自己補上 /api/v1，這裡再寫一次會變成 /api/v1/api/v1/... 然後 404。
const PREVIEW_PATH = "/asr/preview";

export interface AsrPreview {
  text: string;
  /** 實際辨識的引擎；指定的那家掛掉時會是備援。 */
  provider: string;
  /** 後端量到的轉寫耗時，不含上傳與轉檔。 */
  elapsed_seconds?: number;
}

/**
 * 用指定的引擎轉寫一段錄音，讓操作者當場比較各家。只影響這一次，不改任何人
 * 的設定；provider 留空就用部署預設。
 */
export async function previewAsr(
  clip: Blob,
  filename?: string,
  provider = "",
): Promise<AsrPreview> {
  const form = new FormData();
  // 副檔名決定後端暫存檔的 suffix，進而決定 ffmpeg 怎麼解這個檔：上傳的
  // mp3 若冠上 .webm，轉檔就會失敗。錄音沒有檔名，那才是 webm。
  form.append("file", clip, filename || "preview.webm");
  if (provider) form.append("provider", provider);
  const res = await apiFetch(apiUrl(PREVIEW_PATH), {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await parseErrorMessage(res));
  return (await res.json()) as AsrPreview;
}

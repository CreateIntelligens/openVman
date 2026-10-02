export const BROWSER_ASR = "browser";
/** Gemini transcribe-live 串流辨識；台語分流時不用（Gemini 聽不懂台語）。 */
export const GEMINI_STREAM_ASR = "gemini-live";
export const R2T2_STREAM_ASR = "r2t2-live";
/** .35 測試機的串流：選了才用，失敗不換台。 */
export const R2T2_DEV_STREAM_ASR = "r2t2-dev-live";
export const STREAM_ASR_ENGINES = [GEMINI_STREAM_ASR, R2T2_STREAM_ASR, R2T2_DEV_STREAM_ASR] as const;

export function isStreamAsrEngine(provider: string): boolean {
  return STREAM_ASR_ENGINES.some((engine) => engine === provider);
}

/**
 * 在伺服器上跑、音檔要上傳的引擎（跟後端 SERVER_ASR_PROVIDERS 同一組）。沒選過
 * 引擎的人用部署設定的 ASR_PROVIDER，後台已經沒有「全站預設」可以改。
 */
export const SERVER_ASR_ENGINES = ["breeze", "r2t2", "r2t2-dev", "xiaomi", "sensevoice", "openai"] as const;

/** ASR 引擎的顯示名稱與說明。後台「語音」頁、前端設定與聊天室的引擎選單共用。 */
export const ASR_ENGINE_NOTES: Record<string, { label: string; note: string }> = {
  breeze: {
    label: "Breeze-ASR-26",
    note: "臺語會轉寫成華語：語意保留、用字不保留。部署預設用這個。",
  },
  r2t2: {
    label: "Confucius4-R2T2",
    note: "網易有道開源（Qwen3-ASR），華英混合，輸出簡體會自動轉繁；會帶專案詞表。",
  },
  "r2t2-dev": {
    label: "Confucius4-R2T2 dev",
    note: ".35 測試機，同時多句可能卡住；只有選它才用，不當其他引擎的備援。",
  },
  xiaomi: {
    label: "Xiaomi-CocktailASR-1",
    note: "臺語轉寫成華語，輸出簡體會自動轉繁。吵雜環境的辨識較穩。",
  },
  sensevoice: {
    label: "SenseVoice-Small",
    note: "以臺語漢字輸出臺語語音，要保留臺語用字才選它。",
  },
  openai: {
    label: "OpenAI Whisper",
    note: "需要 API 金鑰，語音會送出到外部服務。",
  },
  browser: {
    label: "瀏覽器內建辨識",
    note: "在使用者裝置上辨識，語音不會送到伺服器；部分瀏覽器不支援。",
  },
  "gemini-live": {
    label: "Gemini Live",
    note: "邊講邊出字、講完約 0.5 秒定稿；語音送往 Google。台語分流時改用 Breeze。",
  },
  "r2t2-live": {
    label: "Confucius4-R2T2 串流",
    note: "邊講邊出字，帶專案詞表、定稿轉繁體；台語分流時改用 Breeze 批次。",
  },
  "r2t2-dev-live": {
    label: "Confucius4-R2T2 dev 串流",
    note: ".35 測試機的串流，可能不穩；連不上時退回批次辨識。",
  },
};

export const ASR_ENGINE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(ASR_ENGINE_NOTES).map(([key, value]) => [key, value.label]),
);

export function describeAsrEngine(id: string): { label: string; note: string } {
  return ASR_ENGINE_NOTES[id] ?? { label: id, note: "" };
}

// MediaRecorder 的容器格式依瀏覽器而異；後端會用副檔名決定怎麼解，所以這裡
// 要把實際用的格式對應成正確的副檔名，不能一律寫死 .webm。
export const MIME_SUFFIXES: Array<[string, string]> = [
  ["audio/webm", ".webm"],
  ["audio/ogg", ".ogg"],
  ["audio/mp4", ".mp4"],
];

export function suffixFor(mimeType: string): string {
  const found = MIME_SUFFIXES.find(([type]) => mimeType.startsWith(type));
  return found ? found[1] : ".webm";
}

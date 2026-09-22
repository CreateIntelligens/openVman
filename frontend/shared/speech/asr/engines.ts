export const BROWSER_ASR = "browser";

/** ASR 引擎的顯示名稱與說明。後台「語音」頁、前端設定與聊天室的引擎選單共用。 */
export const ASR_ENGINE_NOTES: Record<string, { label: string; note: string }> = {
  breeze: {
    label: "Breeze-ASR-26",
    note: "臺語會轉寫成華語：語意保留、用字不保留。預設用這個。",
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

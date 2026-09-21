/** ASR 引擎的顯示名稱與說明。後台「語音」頁與聊天室的引擎選單共用。 */
// 選單上只有代號的話，使用者無從判斷該選哪個。寫辨識行為的差異，不寫
// 延遲秒數——那隨文字長度與 GPU 負載變動，標在介面上等於給一個做不到的承諾。
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

export function describeAsrEngine(id: string): { label: string; note: string } {
  return ASR_ENGINE_NOTES[id] ?? { label: id, note: "" };
}

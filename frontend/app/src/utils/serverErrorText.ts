/**
 * 後端錯誤碼轉成訪客看得懂的話。
 *
 * 前台面對的是來賓，不是工程師：「BRAIN_ERROR: HTTP 500」只會讓人以為機器壞了。
 * 原始錯誤碼與訊息留給 console 查，畫面上只說發生什麼、要怎麼做。
 */

const BY_CODE: Record<string, string> = {
  TTS_TIMEOUT: "語音準備得比較久，請再問一次。",
  LLM_OVERLOAD: "現在詢問的人比較多，請稍候再問一次。",
  GATEWAY_TIMEOUT: "查資料花了太久時間，請再問一次。",
  UPLOAD_FAILED: "檔案沒有上傳成功，請換個檔案或稍後再試。",
  INTERNAL_ERROR: "剛剛出了點狀況，請再問一次。",
  BRAIN_UNAVAILABLE: "服務暫時無法使用，請稍後再試，或請現場人員協助。",
  AUTH_FAILED: "登入已經失效，請重新登入。",
  CONNECTION_FAILED: "連線沒有成功，請確認網路後再試。",
};

const FALLBACK = "暫時無法回答，請稍後再試。";

/** 文字聊天走 HTTP 時錯誤碼都是 BRAIN_ERROR，要看狀態碼或網路錯誤才知道是哪一種。 */
function brainErrorText(message: string): string {
  const status = Number(/HTTP (\d{3})/.exec(message)?.[1]);
  if (status === 401 || status === 403) return BY_CODE.AUTH_FAILED;
  if (status === 429) return "問得太快了，請稍等一下再問。";
  if (status === 504 || status === 408) return BY_CODE.GATEWAY_TIMEOUT;
  if (/failed to fetch|networkerror|load failed|network/i.test(message)) {
    return "網路連線中斷，請確認網路後再試。";
  }
  return FALLBACK;
}

export function serverErrorText(code: string, message = "", retryAfterMs?: number): string {
  const text = code === "BRAIN_ERROR" ? brainErrorText(message) : BY_CODE[code] ?? FALLBACK;
  if (!retryAfterMs) return text;
  return `${text}（約 ${Math.max(1, Math.round(retryAfterMs / 1000))} 秒後可以再試）`;
}

/** 全螢幕錯誤的標題：不顯示錯誤碼。 */
export function fatalErrorTitle(code: string): string {
  if (code === "AUTH_FAILED") return "需要重新登入";
  if (code === "AVATAR_RENDERER") return "虛擬人載入失敗";
  return "暫時無法使用";
}

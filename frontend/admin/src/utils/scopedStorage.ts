/**
 * Account-scoped localStorage.
 *
 * 偏好原本寫在扁平的鍵上，跟帳號無關，所以共用瀏覽器時下一個登入的人會繼承
 * 上一個人的專案、角色、TTS 設定。這裡把每個鍵綁到帳號 id 上。
 *
 * 全部走這一層而不是各自呼叫 window.localStorage：Admin 有二十幾處散落的存取
 * 點，逐一改寫既容易漏，之後新增的地方也會忘記綁定。
 */

let scopeId = "";

/** Bind preference storage to an account; "" unbinds (logged out). */
export function setStorageScope(accountId: string): void {
  scopeId = accountId || "";
}

export function currentStorageScope(): string {
  return scopeId;
}

function scopedKey(key: string): string {
  return scopeId ? `${key}::${scopeId}` : key;
}

/**
 * 讀取偏好。這個帳號還沒有自己的值時，沿用未綁定的舊值當起點——既有使用者
 * 升級後不會突然被重設，但之後的寫入都會落在自己的鍵上。
 *
 * 存取本身可能丟例外（無痕模式、瀏覽器封鎖網站資料），所以一律包起來：
 * 讀不到偏好不該讓整個畫面掛掉。
 */
export function readScoped(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    const scoped = window.localStorage.getItem(scopedKey(key));
    if (scoped !== null) return scoped;
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeScoped(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(scopedKey(key), value);
  } catch {
    // 配額已滿或存取被封鎖：偏好存不下來不值得中斷使用者的操作。
  }
}

export function removeScoped(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(scopedKey(key));
    // 未綁定的舊鍵也一併清掉，否則下次讀取又會繼承回來。
    window.localStorage.removeItem(key);
  } catch {
    // 同上，忽略。
  }
}

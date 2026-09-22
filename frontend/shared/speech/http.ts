/**
 * HTTP 抽象轉接介面
 *
 * 允許 shared 語音核心庫在無依賴特定前端（app / admin）的情況下呼叫後端 API。
 * 路徑由 shared 層傳遞完整路徑（例如 `/api/v1/...`）。
 */

export interface HttpAdapter {
  request(path: string, init?: RequestInit): Promise<Response>
  parseError?(res: Response): Promise<string> | string
}

/**
 * 預設的錯誤訊息抽取輔助
 */
export async function extractErrorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data.detail === 'string') return data.detail
    if (data.detail && typeof data.detail === 'object') {
      return data.detail.message || JSON.stringify(data.detail)
    }
    return data.message || data.error || `HTTP ${res.status}`
  } catch {
    return `HTTP ${res.status}`
  }
}

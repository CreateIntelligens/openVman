/** Check session before touching protected assets or initializing one-shot WASM. */
export async function checkMotionAccess(fetcher = fetch, assetUrl = "/static/characters/0624/combined_data.json.gz") {
  const options = { credentials: "same-origin", cache: "no-store" };
  try {
    const session = await fetcher("/api/v1/auth/admin-me", options);
    if (session.status === 401) return { state: "login-required", message: "請先登入 Vman，再載入測試角色。登入頁會另開分頁，完成後回來重新檢查。" };
    if (!session.ok) return { state: "unavailable", message: "暫時無法確認登入狀態，請稍後重新檢查。" };
    const asset = await fetcher(assetUrl, options);
    if (asset.status === 401) return { state: "login-required", message: "登入已過期，請重新登入 Vman。" };
    if (asset.status === 403) return { state: "unavailable", message: "目前帳號無權讀取這個測試角色，請使用有權限的帳號登入。" };
    if (!asset.ok) return { state: "unavailable", message: `無法讀取測試角色資料（HTTP ${asset.status}），請聯絡維護者確認素材與權限。` };
    // Consume the response before the SDK fetches its copy; never expose it
    // through an unprotected URL or relax the character's access controls.
    await asset.arrayBuffer();
    return { state: "available", message: "已確認角色存取權限，按「載入測試角色」開始。" };
  } catch {
    return { state: "unavailable", message: "無法連線確認角色存取權限，請稍後重新檢查。" };
  }
}

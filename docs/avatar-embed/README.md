# openVman Avatar JavaScript SDK 串接指南

openVman Avatar SDK 會直接在客戶網站的 DOM 建立透明虛擬人，不使用 iframe，也不依賴 Vue、React 或客戶網站的 bundler。公開 global 為 `window.OpenVmanAvatar`。

## 串接前準備

- 可由使用者瀏覽器連線的 openVman HTTPS 網址。
- 綁定客戶 hostname 的 Embed API Key。
- 客戶網站的 CSP 允許載入 openVman 的 script、WASM、影片、角色資料與 TTS。
- 第一次 `speak()` 由 click 或 tap 等使用者操作觸發，避免 autoplay 被封鎖。

API Key 會出現在瀏覽器中，不是 server secret。安全邊界是 HTTPS、allowed domains、速率限制，以及 key 的 rotate／disable 機制。

## 最小串接

```html
<button id="openvman-greet" type="button">請虛擬人打招呼</button>

<script src="https://YOUR_OPENVMAN_HOST/openvman-avatar-sdk.js"></script>
<script>
  let avatar;

  OpenVmanAvatar.init({
    apiKey: "PASTE_API_KEY",
    characterId: "000",
  }).then((instance) => {
    avatar = instance;

    avatar.on("speaking", ({ state }) => {
      console.log("speaking", state);
    });

    avatar.on("error", ({ code, message }) => {
      console.error(code, message);
    });
  });

  document.querySelector("#openvman-greet").addEventListener("click", () => {
    avatar?.speak("你好，歡迎使用今天的服務");
  });
</script>
```

script 必須使用完整 openVman URL。若寫成 `/openvman-avatar-sdk.js`，瀏覽器會向客戶自己的網站抓取 SDK。

## 初始化選項

```js
const avatar = await OpenVmanAvatar.init({
  apiKey: "PASTE_API_KEY",
  characterId: "000",
  persona: "default",
  position: "bottom-right",
  width: "min(42vw, 28rem)",
  height: "min(72dvh, 42rem)",
  zIndex: 1000,
  container: document.querySelector("#avatar-stage"),
});
```

| 選項 | 必填 | 預設值 | 說明 |
|---|---:|---|---|
| `apiKey` | 是 | 無 | Embed API Key。 |
| `characterId` | 否 | `000` | `/assets/<id>/` 下的角色 ID。 |
| `persona` | 否 | 空字串 | 保留給後續對話能力；不會改寫 `speak()` 文字。 |
| `position` | 否 | `bottom-right` | 預設懸浮位置，可設為 `bottom-left`。 |
| `width` | 否 | `min(42vw, 28rem)` | CSS width 值。 |
| `height` | 否 | `min(72dvh, 42rem)` | CSS height 值。 |
| `zIndex` | 否 | `2147483000` | 覆寫 root 的 stacking order。 |
| `container` | 否 | `document.body` | 指定時改為填滿該容器，不使用右下角 fixed 位置。容器應建立自己的 positioning context。 |
| `assetsBaseUrl` | 否 | SDK origin 的 `/assets` | 自訂角色資料根路徑，可用相對或絕對 URL。 |

預設會在 viewport 右下角透明懸浮。角色是否真的去背，仍取決於 WebM 素材是否具有 alpha channel。

## JavaScript API

### `await OpenVmanAvatar.init(options)`

載入 vendor JS、WASM 與角色資料後回傳 instance。同一頁只允許一個 WASM runtime：

- 完全相同的設定再次初始化，回傳既有 instance。
- 不同設定再次初始化，拒絕並回報 `INSTANCE_EXISTS`。
- `destroy()` 後不能再次初始化，會回報 `RUNTIME_DISPOSED`；必須重新載入頁面。

### `await avatar.speak(text)`

把原始 `text` 直接送至 `/api/embed/tts`、播放音訊並同步驅動嘴形，不會先交給 LLM 改寫。

```js
document.querySelector("#sale-item").addEventListener("click", async () => {
  await avatar.speak("這款商品目前有八折優惠");
});
```

Promise 會在播放結束或被 `interrupt()` 中止後完成；失敗時會 reject 並派送 `error` 事件。

### `avatar.interrupt()`

立即停止目前播放、清除嘴形狀態並派送 `{ state: "stop" }`。

### `avatar.setPersona(id)`

更新 instance 保存的 persona ID，供後續對話能力使用。第一版 direct SDK 只有直接朗讀，persona 不會改變 `speak()` 的原文。

### `avatar.on(type, handler)`／`avatar.off(type, handler)`

新增或移除同一 JavaScript context 內的事件 handler，不使用 `postMessage`。

### `avatar.destroy()`

停止音訊並移除 SDK 建立的 root、style 與可見資源。vendor WASM 沒有 terminate API，因此 destroy 後必須重新載入頁面才能建立新 runtime。

## 事件

| 事件 | Payload | 說明 |
|---|---|---|
| `ready` | `{ type: "ready" }` | runtime 與角色已可用；在 init 完成後訂閱也會收到。 |
| `speaking` | `{ type, state: "start" \| "stop" }` | 音訊播放狀態。 |
| `error` | `{ type, code, message }` | TTS、授權、資源或 autoplay 錯誤。 |
| `destroyed` | `{ type: "destroyed" }` | instance 已清理。 |

## API Key 與 allowed domains

請在 backend 容器內管理 key：

```bash
docker compose exec backend python -m scripts.embed_keys_cli create \
  --tenant-id tenant-a \
  --domain shop.example.com \
  --note "production avatar SDK"

docker compose exec backend python -m scripts.embed_keys_cli list
docker compose exec backend python -m scripts.embed_keys_cli disable KEY_ID
docker compose exec backend python -m scripts.embed_keys_cli rotate KEY_ID
```

規則只比較 hostname，不包含 scheme、port 或 path：

- `example.com`：只允許根 hostname。
- `*.example.com`：允許子網域，不包含根 hostname。
- `*`：允許任何 hostname，只適合暫時測試。

direct SDK 的 API request 由客戶頁面直接送出，因此瀏覽器 `Origin` 就是客戶網站，backend 會用它驗證 allowed domains。localhost、IP 與正式網域是不同 hostname。

## CSP

若客戶網站有 Content-Security-Policy，至少需要允許 openVman origin：

```http
Content-Security-Policy: script-src 'self' https://YOUR_OPENVMAN_HOST; connect-src 'self' https://YOUR_OPENVMAN_HOST; media-src 'self' https://YOUR_OPENVMAN_HOST; img-src 'self' data: https://YOUR_OPENVMAN_HOST; style-src 'self' 'unsafe-inline'
```

SDK 會建立自己的 inline style 與 element style，因此上例允許 `style-src 'unsafe-inline'`。若客戶政策禁止 inline style，目前版本需先由 openVman 擴充 nonce／外部 stylesheet 支援；不要用全面移除 CSP 作為修正方式。

## 公開資源與端點

| 路徑 | 用途 |
|---|---|
| `/openvman-avatar-sdk.js` | IIFE SDK。 |
| `/sdk/runtime/OpenVmanAvatarRuntime.js` | 內部 runtime 公開別名。 |
| `/sdk/runtime/OpenVmanAvatarRuntime.wasm` | 內部 WASM 公開別名。 |
| `/assets/<characterId>/combined_data.json.gz` | 角色驅動資料。 |
| `/assets/<characterId>/01.webm` | 透明角色影片。 |
| `/api/embed/tts` | Bearer API Key 保護的 TTS。 |

`/embed/avatar`、`/vman-embed.js` 與 `<vman-avatar>` 已不是支援的串接方式。

## 錯誤碼

| 代碼 | 意義 |
|---|---|
| `INVALID_OPTIONS` | 缺少 API Key 或朗讀文字。 |
| `INSTANCE_EXISTS` | 同頁已有不同設定的 runtime。 |
| `RUNTIME_DISPOSED` | runtime 已 destroy，必須重新載入頁面。 |
| `DOM_CONFLICT` | 宿主頁已占用 vendor 固定 DOM ID。 |
| `RESOURCE_LOAD_FAILED` | vendor JS、WASM 或角色資源載入失敗。 |
| `API_ERROR` | 瀏覽器可讀取的 API `401`／`403`。 |
| `TTS_FAILED` | TTS、音訊解碼或 CORS 阻擋失敗；不在 allowlist 時瀏覽器可能只會提供 `Failed to fetch`。 |
| `AUTOPLAY_BLOCKED` | 瀏覽器要求先有 click／tap 等 user gesture。 |

backend 也可能回傳 `429` 並附 `Retry-After`，表示該 key 超過速率限制。

## 排錯

### SDK 或 runtime 404

確認 script 使用完整 openVman URL，並確認 `avatar-sdk` image 已建置且 service 正常運行。

### HTTP 401／403

確認 key 未 disable／rotate，並檢查瀏覽器網址的 hostname 是否在 allowed domains。用瀏覽器 Network 面板查看 `/api/embed/tts` 的 response。

### 有角色但沒有聲音

第一次 `speak()` 請直接放在 click／tap handler 內。確認客戶網站與 openVman 都是 HTTPS，分頁未靜音。

### 角色有矩形背景

SDK root 本身是透明的；矩形背景通常來自不含 alpha 的 WebM 素材，必須更換角色素材。

### CSP 或 CORS 錯誤

Console 會指出被阻擋的 resource type。CSP 要在客戶網站調整；CORS header 要在 openVman edge 調整。不要把 API endpoint 設為任意反射 Origin，授權 CORS 應由 backend 驗證 key 與 allowlist 後產生。

## 瀏覽器與授權

SDK 依賴 ES2022、Fetch、Web Audio、WebAssembly、WebM 與透明 Canvas，應使用近期 Chrome、Edge、Firefox 或 Safari 實機驗證。每次對外發布前，至少要從不同 origin 測試成功 init、`speak()`、`interrupt()`、403、destroy 與行動裝置尺寸。

avatar runtime 與角色資料可能包含第三方著作。對外提供前，仍須取得引擎嵌入／再分發與角色資料的書面授權；公開名稱改為 openVman 不會改變原始著作權歸屬。

# openVman Avatar JavaScript SDK 串接指南

openVman Avatar SDK 會直接在宿主網站的 DOM 建立透明虛擬人，不使用 iframe，也不依賴 Vue、React 或宿主網站的 bundler。公開 global 為 `window.OpenVmanAvatar`。

SDK 只提供角色渲染、音訊播放與嘴形同步，不開放 openVman 的 Brain、Chat、ASR 或 TTS。外部網站自行產生音訊後交給 SDK，因此初始化不需要 API Key，也不會呼叫 `/api/embed/*`。

## 串接前準備

- 使用者瀏覽器可連線的 openVman HTTPS 網址。
- 宿主網站的 CSP 允許載入 openVman 的 script、WASM、影片與角色資料。
- 第一次播放由 click、tap 或檔案選擇等使用者操作觸發，避免 autoplay 被封鎖。
- 完整音訊可使用瀏覽器支援解碼的格式；串流 PCM 固定為 16 kHz、mono、signed 16-bit little-endian samples。

## 最小串接

```html
<input id="avatar-audio" type="file" accept="audio/*">
<button id="avatar-stop" type="button">停止</button>

<script src="https://YOUR_OPENVMAN_HOST/openvman-avatar-sdk.js"></script>
<script>
  const avatarPromise = OpenVmanAvatar.init({ characterId: "000" });

  document.querySelector("#avatar-audio").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const avatar = await avatarPromise;
    await avatar.playAudio(file);
  });

  document.querySelector("#avatar-stop").addEventListener("click", async () => {
    const avatar = await avatarPromise;
    avatar.interrupt();
  });
</script>
```

script 必須使用完整 openVman URL。若寫成 `/openvman-avatar-sdk.js`，瀏覽器會向宿主網站自己的 origin 抓取 SDK。

可直接開啟 [embed-minimal.html](../../examples/embed-minimal.html) 作為完整範例，並將 SDK script URL 改成部署網址。

## 初始化選項

```js
const avatar = await OpenVmanAvatar.init({
  characterId: "000",
  position: "bottom-right",
  width: "min(42vw, 28rem)",
  height: "min(72dvh, 42rem)",
  zIndex: 1000,
  container: document.querySelector("#avatar-stage"),
});
```

| 選項 | 必填 | 預設值 | 說明 |
|---|---:|---|---|
| `characterId` | 否 | `000` | `/assets/<id>/` 下的角色 ID，可用 `OpenVmanAvatar.listCharacters()` 查詢可用清單。 |
| `position` | 否 | `bottom-right` | 預設懸浮位置，可設為 `bottom-left`。 |
| `width` | 否 | `min(42vw, 28rem)` | CSS width 值。 |
| `height` | 否 | `min(72dvh, 42rem)` | CSS height 值。 |
| `zIndex` | 否 | `2147483000` | 覆寫 root 的 stacking order。 |
| `container` | 否 | `document.body` | 指定時改為填滿該容器，不使用 viewport 懸浮位置。 |
| `assetsBaseUrl` | 否 | SDK origin 的 `/assets` | 自訂角色資料根路徑，可用相對或絕對 URL。 |

同一頁只允許一個 WASM runtime。完全相同的設定會回傳既有 instance；不同設定會回報 `INSTANCE_EXISTS`。`destroy()` 後必須重新載入頁面才能再次初始化。

## JavaScript API

### `await OpenVmanAvatar.listCharacters()`

回傳目前可用角色清單，可在 `init()` 前呼叫，不需要 instance。只列出素材完整（影片與驅動資料齊全）的角色，回傳 `{ charId, label }[]`。

```js
const characters = await OpenVmanAvatar.listCharacters();
for (const { charId, label } of characters) {
  const option = document.createElement("option");
  option.value = charId;
  option.textContent = label;
  characterSelect.append(option);
}
```

### `await avatar.playAudio(source)`

接受 `Blob` 或 `ArrayBuffer`，由瀏覽器解碼、播放並同步驅動嘴形。新的 `playAudio()` 會中止並取代前一次完整音訊。

```js
const response = await fetch("https://YOUR_AUDIO_SERVICE/example.wav");
await avatar.playAudio(await response.arrayBuffer());
```

### `await avatar.pushPcm(chunk)`

接受 `Int16Array` PCM chunk。SDK 會按照呼叫順序排入 Web Audio 時間軸，適合外部 TTS 的串流結果。

```js
for await (const chunk of pcmStream) {
  await avatar.pushPcm(chunk);
}
```

每個 chunk 必須是 16 kHz、單聲道、signed 16-bit PCM samples。若網路 payload 是 bytes，宿主應先處理 byte order 與 alignment，再建立 `Int16Array`。

### `avatar.interrupt()`

立即停止完整音訊與 PCM queue，清除嘴形狀態並派送 `{ state: "stop" }`。

### `avatar.on(type, handler)`／`avatar.off(type, handler)`

新增或移除同一 JavaScript context 內的事件 handler。

### `avatar.destroy()`

停止音訊並移除 SDK 建立的 root、style 與可見資源。vendor WASM 沒有 terminate API，因此 destroy 後必須重新載入頁面才能建立新 runtime。

## 事件

| 事件 | Payload | 說明 |
|---|---|---|
| `ready` | `{ type: "ready" }` | runtime 與角色已可用；在 init 完成後訂閱也會收到。 |
| `speaking` | `{ type, state: "start" \| "stop" }` | 音訊播放狀態。 |
| `error` | `{ type, code, message }` | 音訊、資源或 autoplay 錯誤。 |
| `destroyed` | `{ type: "destroyed" }` | instance 已清理。 |

## CSP

宿主網站若有 Content-Security-Policy，至少需允許 openVman origin：

```http
Content-Security-Policy: script-src 'self' https://YOUR_OPENVMAN_HOST; connect-src 'self' https://YOUR_OPENVMAN_HOST; media-src 'self' https://YOUR_OPENVMAN_HOST; style-src 'self' 'unsafe-inline'
```

SDK 會建立 inline style 與 element style，因此目前需要 `style-src 'unsafe-inline'`。

## 公開資源

| 路徑 | 用途 |
|---|---|
| `/openvman-avatar-sdk.js` | IIFE SDK。 |
| `/sdk/runtime/OpenVmanAvatarRuntime.js` | 內部 runtime 公開別名。 |
| `/sdk/runtime/OpenVmanAvatarRuntime.wasm` | 內部 WASM 公開別名。 |
| `/characters` | 可用角色清單（唯讀，無需驗證）。 |
| `/assets/<characterId>/combined_data.json.gz` | 角色驅動資料。 |
| `/assets/<characterId>/01.webm` | 透明角色影片。 |

`/api/embed/*`、`/ws/embed/*`、`/embed/avatar`、`/vman-embed.js` 與 `<vman-avatar>` 都不是支援的串接面。openVman 原本內部使用的 `/api/*`、`/ws/*`、`/tts/*` 不屬於 Avatar SDK 公開契約。

## 錯誤碼

| 代碼 | 意義 |
|---|---|
| `INVALID_OPTIONS` | 初始化選項無效。 |
| `INSTANCE_EXISTS` | 同頁已有不同設定的 runtime。 |
| `RUNTIME_DISPOSED` | runtime 已 destroy，必須重新載入頁面。 |
| `DOM_CONFLICT` | 宿主頁已占用 vendor 固定 DOM ID。 |
| `RESOURCE_LOAD_FAILED` | vendor JS、WASM 或角色資源載入失敗。 |
| `AUDIO_PLAYBACK_FAILED` | 音訊讀取、解碼或播放失敗。 |
| `AUTOPLAY_BLOCKED` | 瀏覽器要求先有 click／tap 等 user gesture。 |

## 排錯

### SDK 或 runtime 404

確認 script 使用完整 openVman URL，並確認 `admin` service 已建置最新 SDK 且正常運行。

### 有角色但沒有聲音

第一次 `playAudio()` 或 `pushPcm()` 應直接放在使用者操作 handler 內，並確認分頁未靜音。完整音訊還需使用瀏覽器支援的編碼。

### PCM 有雜音或速度錯誤

確認資料是 16 kHz、mono、signed 16-bit PCM，而且 byte order 與 chunk 邊界正確。不要把 WAV header 一起傳給 `pushPcm()`。

### 角色有矩形背景

SDK root 本身是透明的；矩形背景通常來自不含 alpha 的 WebM 素材，必須更換角色素材。

## 瀏覽器與授權

SDK 依賴 ES2022、Fetch、Web Audio、WebAssembly、WebM 與透明 Canvas，應使用近期 Chrome、Edge、Firefox 或 Safari 實機驗證。每次對外發布前，至少要從不同 origin 測試 init、`playAudio()`、`pushPcm()`、`interrupt()`、destroy 與行動裝置尺寸。

avatar runtime 與角色資料可能包含第三方著作。對外提供前，仍須取得引擎嵌入／再分發與角色資料的書面授權；公開名稱改為 openVman 不會改變原始著作權歸屬。

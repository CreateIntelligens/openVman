# openVman Avatar JavaScript SDK 串接指南

openVman Avatar SDK 會直接在宿主網站的 DOM 建立透明虛擬人，不使用 iframe，也不依賴 Vue、React 或宿主網站的 bundler。公開 global 為 `window.OpenVmanAvatar`。

SDK 有兩種使用方式。預設是**播放模式**：只做角色渲染、音訊播放與嘴形同步，外部網站自行產生音訊後交給 SDK，初始化不需要任何金鑰。另一種是**對話模式**：初始化時提供 embed key（或在同源頁面沿用既有 session），即可用 `ask()` 讓 openVman 完成「回答 + 語音 + 嘴形」一整輪。未提供對話選項時，SDK 完全不會發出 chat 或 TTS 請求。

## 串接前準備

- 使用者瀏覽器可連線的 openVman HTTPS 網址。
- 宿主網站的 CSP 允許載入 openVman 的 script、WASM、影片與角色資料。
- 第一次播放由 click、tap 或檔案選擇等使用者操作觸發，避免 autoplay 被封鎖。
- 完整音訊可使用瀏覽器支援解碼的格式；串流 PCM 固定為 16 kHz、mono、signed 16-bit little-endian samples。

## 最小串接

```html
<input id="avatar-audio" type="file" accept="audio/*">
<button id="avatar-stop" type="button">停止</button>

<script src="https://YOUR_OPENVMAN_HOST/static/sdk/openvman-avatar-sdk.js"></script>
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

script 必須使用完整 openVman URL。若寫成 `/static/sdk/openvman-avatar-sdk.js`，瀏覽器會向宿主網站自己的 origin 抓取 SDK。

可直接開啟 [embed-minimal.html](../../../examples/embed-minimal.html) 作為完整範例，並將 SDK script URL 改成部署網址。

## 初始化選項

```js
const avatar = await OpenVmanAvatar.init({
  characterId: "000",
  position: "bottom-right",
  width: "min(42vw, 28rem)",
  height: "min(72dvh, 42rem)",
  zIndex: 1000,
  container: document.querySelector("#avatar-stage"),
  audioOutput: "speaker",
});
```

| 選項 | 必填 | 預設值 | 說明 |
|---|---:|---|---|
| `characterId` | 否 | `000` | `/static/characters/<id>/` 下的角色 ID，可用 `OpenVmanAvatar.listCharacters()` 查詢可用清單。 |
| `position` | 否 | `bottom-right` | 預設懸浮位置，可設為 `bottom-left`。 |
| `width` | 否 | `min(42vw, 28rem)` | CSS width 值。 |
| `height` | 否 | `min(72dvh, 42rem)` | CSS height 值。 |
| `zIndex` | 否 | `2147483000` | 覆寫 root 的 stacking order。 |
| `container` | 否 | `document.body` | 指定時改為填滿該容器，不使用 viewport 懸浮位置。 |
| `assetsBaseUrl` | 否 | SDK origin 的 `/static/characters` | 自訂角色資料根路徑，可用相對或絕對 URL。 |
| `cacheAssets` | 否 | `true` | 把播放程式與人物檔存進瀏覽器（見下方「素材存在瀏覽器」）。設 `false` 則每次都從網路下載、不寫入瀏覽器。 |
| `audioLeadMs` | 否 | `150` | `pushPcm` 每段話開頭先扣住的毫秒數（0～2000）：收滿這段時間的 PCM 再一起送進嘴型模型並開始播，照播放速度送 PCM 時嘴才張得開。這段期間 `speaking` 不會先發 `start`。設 `0` 則收到就播（舊行為）。宿主若已自己扣住開頭，請設 `0`，避免延遲疊加。 |
| `audioOutput` | 否 | `speaker` | `speaker` 由 SDK 播放音訊；`silent` 保留播放時間軸與嘴型但靜音，適用於宿主另行播放同一段音訊的情境。`silent` 以頁面時鐘排程、不建立 AudioContext，沒被使用者點過的視窗（開機後的 kiosk、`window.open` 開出的視窗）也能對嘴，不會丟 `AUTOPLAY_BLOCKED`。 |
| `embedKey` | 否 | 無 | 對話模式用的 embed key。設定後 `ask()` 會帶 `X-Embed-Key` 且不送 cookie；未設定則以同源 session cookie 呼叫。 |
| `projectId` | 否 | 後端預設 | `ask()` 使用的專案 ID。使用 embed key 時必須與該金鑰綁定的專案一致，否則回 403。 |
| `personaId` | 否 | 後端預設 | `ask()` 使用的人格 ID。 |
| `tts` | 否 | 後端預設 | `{ provider, voice, language }`，指定 `ask()` 合成語音的 TTS 供應商與音色；`language` 是回答要唸的語言（`zh`、`en`、`nan`…），`nan` 且專案開了台語分流時改用台語引擎。 |

`init()` 先把播放程式與人物檔都拿到（瀏覽器存檔或網路），才建立 runtime 與畫面。連不上、逾時或 5xx 時自動再試兩次（間隔 1 秒、3 秒）；仍失敗就回 `RESOURCE_LOAD_FAILED`，頁面上沒有留下任何東西，可以直接再呼叫 `init()`，不必重新整理。人物影片解碼或播放失敗（檔案已拿到之後）仍會讓這一頁不能再建 runtime（`RUNTIME_DISPOSED`）。

同一頁只允許一個 WASM runtime。完全相同的設定會回傳既有 instance；不同設定會回報 `INSTANCE_EXISTS`。`embedKey`、`projectId`、`personaId` 與 `tts` 一併計入設定比對，因此只改對話選項再次 `init()` 同樣會被拒絕。`destroy()` 後必須重新載入頁面才能再次初始化。

### 素材存在瀏覽器

預設（`cacheAssets: true`）播放程式（`OpenVmanAvatarRuntime.js`／`.wasm`）與人物檔（`combined_data.json.gz`、`01.webm`）第一次下載後存進嵌入頁面網域的 Cache Storage，之後開頁面不必再下載，openVman 暫時連不上時人物也照樣出現。對話與語音（`ask()`）每次都要連到 openVman，連不上時照常回錯誤。

- 用存檔前先向 openVman 確認（只等回應標頭，最多 3 秒）：
  - 回 401、403、404（金鑰撤銷、人物取消指派或刪除、換了沒有權限的帳號）：清掉那組存檔，`init()` 失敗，不會先顯示。
  - 連不上、逾時、5xx，或回的是網頁而不是檔案（登入頁、captive portal）：當作暫時離線，用存檔。
  - `Last-Modified` 與 `Content-Length` 都跟存檔相同：立刻中斷那個請求，不下載內容。
  - 有變：這次照樣用存檔，背景下載新版，整組（播放程式兩支一組、人物兩支一組）換好後下一次開頁面生效。
- 因此有存檔時，每次開頁面仍多一次往返（等標頭）；openVman 連不上時要等到逾時（最多 3 秒）才用存檔。
- 離線期間存檔會一直留著，登出也不會清：同一台瀏覽器之前看過的專案人物，openVman 連不上時仍顯示得出來。30 天沒用到的那組會在之後的載入時清掉。
- 第一次下載時連不上、逾時（等標頭 15 秒、下載 120 秒）、5xx 或下載到一半中斷，自動再試兩次。
- `avatar.assetsFromCache` 為 `true` 表示這次 `init()` 完全沒有下載。
- 嵌入頁面必須是 https（或 localhost）才有 Cache Storage；隱私模式、使用者清除網站資料、瀏覽器空間不足時存檔會不見，就回到第一次下載。這些情況與快取出錯都只會改走網路，不會讓 `init()` 失敗。
- 存檔的播放程式與人物影片以 `blob:` 網址載入。頁面的 CSP 不允許 `blob:` 腳本（`script-src`）或媒體（`media-src`）時，那一項改從原網址載入，此時 openVman 連不上就載不到。播放程式本身仍需要 `'unsafe-eval'` 與 `'wasm-unsafe-eval'`（跟以前一樣）。
- SDK 本體（`openvman-avatar-sdk.js`）由瀏覽器的 HTTP 快取處理：`max-age=300` 加上 `stale-while-revalidate=2592000`，播放程式兩支同樣加上。Chromium 實測：過期後 openVman 連不上，仍用舊的 SDK 載起來；Safari、Firefox 尚未驗證。SDK 換版後，訪客要再開一次頁面才會拿到新版。
- 第一次開頁面要等人物影片整檔下載完才出畫面（以前邊下載邊播），影片 1～13 MB。

## 對話模式

設定對話選項後，`await avatar.ask(text)` 會完成一整輪：送出 `POST /api/v1/chat/stream`，回答每寫完一句就派送 `sentence` 事件，並以該句呼叫 `POST /api/v1/tts/stream`（`format: "pcm16k"`）串流合成：收到第一段 16 kHz PCM 就開始播放並驅動嘴形，不必等整句合成完，接在前一段後面播放。同時只送一個語音請求，合成期間到的句子會併進下一個請求；前一段還在播時下一段已經可以開始合成。部署沒有串流合成路由（回 404／405）時，該 instance 之後改用 `POST /v1/audio/speech` 整句合成。回答結束時派送一次 `reply` 事件（完整回答），Promise 在語音全部播完後 resolve，回傳回覆文字。需要知道開口時機請監聽 `speaking` 事件；一輪中若下一句還沒合成好，`speaking` 可能先 `stop` 再 `start`。

同一個 instance 的每次 `ask()` 都會沿用同一組 `session_id`，因此後端看得到完整上下文。新的 `ask()`、`interrupt()` 或 `destroy()` 會連同上一輪的串流、還沒送出的合成與正在播的語音一起中止，不會兩段答案疊在一起；在回答結束前被中止的 `ask()` 會 resolve 為已收到的句子，不派送 `reply`，這一輪也不寫入對話紀錄；回答已結束、只剩語音在播時才中止，則 resolve 為完整回答（`reply` 已派送過）。

部署沒有串流路由（回 404／405）而 `POST /api/v1/chat` 可用時，該 instance 之後的 `ask()` 都直接走 `/api/v1/chat`，等整段回答後再合成。

### 外部網站（embed key）

embed key 是公開識別碼，不是密鑰，可以直接寫在前端。實際權限由後端的 origin allowlist、專案綁定、速率與每日配額決定，請在後台「專案與權限 → 網站嵌入金鑰」分頁建立並限定允許的 origin。每輪 `ask()` 會用掉 1 個對話串流請求，加上 1 個以上的語音請求（合成期間到的句子會併進同一個請求），設定速率與每日配額時請一併計入。每日配額在台北時間午夜歸零。

```html
<button id="ask" type="button">問一句</button>

<script src="https://YOUR_OPENVMAN_HOST/static/sdk/openvman-avatar-sdk.js"></script>
<script>
  const avatarPromise = OpenVmanAvatar.init({
    characterId: "000",
    embedKey: "ovk_YOUR_EMBED_KEY",
    projectId: "your-project",
    personaId: "default",
    tts: { provider: "voxcpm", voice: "zh-female" },
  });

  document.querySelector("#ask").addEventListener("click", async () => {
    const avatar = await avatarPromise;
    avatar.on("reply", ({ text }) => {
      console.log("回覆：", text);
    });

    try {
      await avatar.ask("請介紹一下你們的服務");
    } catch (error) {
      console.error(error.code, error.message);
    }
  });
</script>
```

請求會帶 `X-Embed-Key` 且 `credentials: "omit"`，所以宿主網站的 cookie 不會外送。

### 同源頁面（session）

在已登入 openVman 的同源頁面省略 `embedKey` 即可，請求改以 `credentials: "include"` 送出，沿用既有 session cookie。

```js
const avatar = await OpenVmanAvatar.init({
  characterId: "000",
  projectId: "your-project",
});

const reply = await avatar.ask("今天有哪些待辦？");
```

### 對話事件與錯誤

`ask()` 期間會派送 `sentence`、`reply`、`speaking` 與 `error` 事件；`error` 事件與 `ask()` reject 的錯誤內容相同，方便集中處理。`sentence`（`{ index, text }`）適合逐句顯示字幕，所有句子依序接起來等於 `reply` 的 `text`。

```js
avatar.on("sentence", ({ text }) => appendToBubble(text));
avatar.on("reply", ({ text }) => replaceBubble(text));
avatar.on("error", ({ code, retryAfterSeconds }) => {
  if (code === "RATE_LIMITED") {
    showNotice(`請於 ${retryAfterSeconds ?? 60} 秒後再試。`);
  }
});
```

| 代碼 | 觸發情境 | 建議處理 |
|---|---|---|
| `UNAUTHORIZED` | HTTP 401 或 403：金鑰無效、已停用、origin 不在 allowlist，或 `projectId` 與金鑰綁定的專案不符。 | 停用對話 UI，不要重試。 |
| `RATE_LIMITED` | HTTP 429：超過每分鐘速率或每日配額；有 `Retry-After`（或串流 `error` 事件的 `retry_after_ms`）時會帶 `retryAfterSeconds`。 | 依 `retryAfterSeconds` 退避後再試。 |
| `CHAT_FAILED` | 其他對話失敗：網路錯誤、後端 5xx、串流中途的 `error` 事件，或沒有收到完整回答。已開口的部分會停掉。 | 提示稍後再試。 |
| `SPEECH_FAILED` | 語音合成失敗。SDK 仍會讀完回答並派送 `reply` 事件後才 reject，宿主可只顯示文字。 | 降級為純文字回覆。 |

若初始化時設定 `audioOutput: "silent"`，`ask()` 一樣會驅動嘴型並正常 resolve，只是 SDK 不出聲，適合宿主自行播放同一段語音的情境。

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

### `await avatar.ask(text)`

只在對話模式可用，完成一整輪對話並回傳回覆文字，詳見上方[對話模式](#對話模式)。

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

如果宿主已播放相同音訊，初始化時請設定 `audioOutput: "silent"`。SDK 仍會排程 PCM 並驅動嘴型，但不會將訊號送至喇叭，可避免重複出聲。

### `avatar.interrupt()`

立即停止完整音訊與 PCM queue，清除嘴形狀態並派送 `{ state: "stop" }`；`ask()` 進行中時一併中止對話串流與還沒送出的合成。

### `avatar.on(type, handler)`／`avatar.off(type, handler)`

新增或移除同一 JavaScript context 內的事件 handler。

### `avatar.destroy()`

停止音訊並移除 SDK 建立的 root、style 與可見資源。vendor WASM 沒有 terminate API，因此 destroy 後必須重新載入頁面才能建立新 runtime。

## 事件

| 事件 | Payload | 說明 |
|---|---|---|
| `ready` | `{ type: "ready" }` | runtime 與角色已可用；在 init 完成後訂閱也會收到。 |
| `speaking` | `{ type, state: "start" \| "stop" }` | 音訊播放狀態。`start` 在第一段音訊真正開始播時才派送；佇列播完後再等 300 ms 沒有新音訊才派送 `stop`（`audioLeadMs: 0` 時播完立即派送），照播放速度送 PCM 的空檔不會斷成好幾段。 |
| `reply` | `{ type, text, sessionId, traceId }` | 對話模式取得回覆文字，於語音合成前派送。`sessionId` 是這個 instance 的對話 ID，`traceId` 是後端這一輪的追蹤 ID（後端沒給時為空字串），可用來對照後端 log 與對話紀錄。 |
| `error` | `{ type, code, message, retryAfterSeconds? }` | 音訊、資源、autoplay 或對話錯誤；`retryAfterSeconds` 只在 `RATE_LIMITED` 出現。 |
| `destroyed` | `{ type: "destroyed" }` | instance 已清理。 |

## CSP

宿主網站若有 Content-Security-Policy，至少需允許 openVman origin：

```http
Content-Security-Policy: script-src 'self' https://YOUR_OPENVMAN_HOST; connect-src 'self' https://YOUR_OPENVMAN_HOST; media-src 'self' https://YOUR_OPENVMAN_HOST; style-src 'self' 'unsafe-inline'
```

SDK 會建立 inline style 與 element style，因此目前需要 `style-src 'unsafe-inline'`。

## 公開資源

人物大多屬於某個專案（2026-10-16 起全部人物都是專案專屬），不帶憑證讀不到素材。SDK 的 `<video>` 請求帶不了自訂標頭，請由你的網站伺服器轉發 `/static/characters/`，在轉發時加上 `X-Embed-Key` 與金鑰白名單內的 `Origin`，金鑰只放在伺服器端。nginx 範例：

```nginx
location /static/characters/ {
    proxy_pass https://<openVman 網址>/static/characters/;
    proxy_ssl_server_name on;
    proxy_set_header Origin "https://your-site.example";
    proxy_set_header X-Embed-Key "<embed key>";
}
```

| 路徑 | 用途 |
|---|---|
| `/static/sdk/openvman-avatar-sdk.js` | IIFE SDK。 |
| `/static/sdk/runtime/OpenVmanAvatarRuntime.js` | 內部 runtime 公開別名。 |
| `/static/sdk/runtime/OpenVmanAvatarRuntime.wasm` | 內部 WASM 公開別名。 |
| `/api/v1/characters` | 可用角色清單（唯讀）。不帶憑證只列全域公開的人物；帶 `X-Embed-Key` 時只列金鑰允許的人物：全域公開人物加上金鑰綁定專案的專屬與指派人物，列出的人物素材都讀得到。 |
| `/static/characters/<characterId>/combined_data.json.gz` | 角色驅動資料。專案專屬人物要帶 `X-Embed-Key`。 |
| `/static/characters/<characterId>/01.webm` | 透明角色影片。專案專屬人物要帶 `X-Embed-Key`。 |
| `/api/v1/chat` | 對話模式的回答端點（需 embed key 或 session）。 |
| `/api/v1/chat/stream` | 同一個回答以 SSE 逐句送出，SDK 的 `ask()` 預設走這條（需 embed key 或 session；事件格式見[串接快速開始](../integration-quickstart.md)）。 |
| `/api/v1/tts/stream` | 對話模式的語音合成端點，SDK 帶 `format: "pcm16k"` 邊收邊播（需 embed key 或 session）。 |
| `/v1/audio/speech` | 整句語音合成；部署沒有 `/api/v1/tts/stream` 時 SDK 退回這條（需 embed key 或 session）。 |

`/api/embed/*`、`/ws/embed/*`、`/embed/avatar`、`/vman-embed.js` 與 `<vman-avatar>` 都不是支援的串接面，且已全數回 404。除上表列出者外，openVman 內部使用的 `/api/v1/*` 其餘端點不屬於 Avatar SDK 公開契約；embed key 也只能存取上表所列路徑。

## 錯誤碼

| 代碼 | 意義 |
|---|---|
| `INVALID_OPTIONS` | 初始化選項無效。 |
| `INSTANCE_EXISTS` | 同頁已有不同設定的 runtime。 |
| `RUNTIME_DISPOSED` | runtime 已 destroy，或人物影片在 runtime 建立後解碼／播放失敗，必須重新載入頁面。 |
| `DOM_CONFLICT` | 宿主頁已占用 vendor 固定 DOM ID。 |
| `RESOURCE_LOAD_FAILED` | vendor JS、WASM 或角色資源載入失敗。 |
| `AUDIO_PLAYBACK_FAILED` | 音訊讀取、解碼或播放失敗。 |
| `AUTOPLAY_BLOCKED` | 瀏覽器要求先有 click／tap 等 user gesture（只有 `audioOutput: "speaker"` 會發生）。 |
| `WEBGL_CONTEXT_LOST` | 瀏覽器丟掉了嘴型用的 WebGL 畫布。人物影片照常播放、不再貼嘴型，直到重新載入頁面；這個錯誤只透過 `error` 事件通知，不會讓呼叫失敗。 |
| `UNAUTHORIZED` | 對話請求回 401 或 403。 |
| `RATE_LIMITED` | 對話請求回 429，可能帶 `retryAfterSeconds`。 |
| `CHAT_FAILED` | 對話請求失敗或回應缺少 `reply`。 |
| `SPEECH_FAILED` | 語音合成請求失敗。 |

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

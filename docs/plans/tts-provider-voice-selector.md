# TTS Provider / Voice Selector

> 2026-03-24 — feature/brain

## Goal

讓使用者在 Chat 頁面選擇 TTS provider 和 voice/character，取代目前的自動 fallback-only 行為。

## Current State

- `POST /v1/audio/speech` 接受 `{ input, voice }` — 無 provider 選擇
- `TTSRouterService.synthesize()` 走固定 fallback chain: IndexTTS → GCP → AWS → Edge-TTS
- `voice` 參數已存在，各 adapter 用 `voice_hint` 處理
- IndexTTS 服務提供 `GET /audio/voices` 回傳可用角色
- 前端 `synthesizeSpeech()` 只送 `input`，沒帶 voice 或 provider

## Design

### Provider ID 對照表

各 adapter 的 `provider_name` 屬性作為 canonical ID，前後端統一使用：

| Adapter | `provider_name` | 前端顯示名 |
|---------|-----------------|------------|
| IndexTTSAdapter | `index` | IndexTTS |
| GCPTTSAdapter | `gcp` | GCP TTS |
| AWSPollyAdapter | `aws` | AWS Polly |
| EdgeTTSAdapter | `edge-tts` | Edge TTS |

`TTSRouterService.synthesize(provider=...)` 用 `provider_name` 查找 adapter。
`"auto"` 和 `""` 走完整 fallback chain。

### Backend

#### 1. `GET /v1/tts/providers`

回傳啟用中的 provider 清單 + voice 選項。

Response:
```json
[
  { "id": "auto", "name": "自動", "voices": [], "default_voice": "" },
  { "id": "index", "name": "IndexTTS", "default_voice": "hayley", "voices": ["jay", "hayley"] },
  { "id": "gcp", "name": "GCP TTS", "default_voice": "cmn-TW-Standard-A", "voices": ["cmn-TW-Standard-A"] },
  { "id": "aws", "name": "AWS Polly", "default_voice": "Zhiyu", "voices": ["Zhiyu"] },
  { "id": "edge-tts", "name": "Edge TTS", "default_voice": "zh-TW-HsiaoChenNeural", "voices": ["zh-TW-HsiaoChenNeural"] }
]
```

- IndexTTS voices: 用 `_health_http`（既有的 `SharedAsyncClient`）呼叫 `GET {tts_index_url}/audio/voices` 動態取得。若 IndexTTS 不可達，該 provider 的 `voices` 回空陣列，`default_voice` 仍從 config 取。
- 其他 provider: 從 config 取預設值（靜態）
- 未啟用的 provider 不列出
- `auto` 永遠在最前面

路由放在 `main.py`（與 `/v1/audio/speech` 同層），tag 為 `TTS`，path 為 `/v1/tts/providers`（與既有 `/v1/audio/speech` 前綴一致）。

#### 2. 修改 `SpeechRequest`

```python
class SpeechRequest(BaseModel):
    input: str
    voice: str = ""
    provider: str = ""          # NEW: "" or "auto" = fallback chain
    response_format: str = "wav"
    speed: float = 1.0
```

向下相容：既有 client 不帶 `provider` 時預設 `""`，行為不變。

#### 3. 修改 `TTSRouterService.synthesize()`

新增 `provider` 參數：

- `provider == "" or "auto"`: 走完整 fallback chain（現有行為不變）
- `provider == "index"` 等: 用 `provider_name` 從 chain 找出對應 adapter 直接呼叫
  - 成功 → 正常回傳
  - 失敗 → fallback 到 Edge-TTS（最後一個 adapter），response 帶 fallback 資訊
  - Edge-TTS 也失敗 → raise RuntimeError（與現有 chain-exhausted 行為一致）

#### 4. Fallback 回傳機制

不修改 `NormalizedTTSResult`（frozen dataclass）。改用 wrapper dataclass：

```python
@dataclass(frozen=True, slots=True)
class SynthesisOutput:
    result: NormalizedTTSResult
    fallback: bool = False
    fallback_reason: str = ""
```

`synthesize()` 回傳 `SynthesisOutput`。`create_speech()` 讀取 fallback 欄位：

```
X-TTS-Fallback: true
X-TTS-Fallback-Reason: IndexTTS timeout after 10s
```

現有的 auto chain 模式回傳 `SynthesisOutput(result=..., fallback=False)`，呼叫端不需改動。

### Frontend

#### 5. api.ts

```typescript
export interface TtsProvider {
  id: string;
  name: string;
  default_voice: string;
  voices: string[];
}

export async function fetchTtsProviders(): Promise<TtsProvider[]> {
  const res = await fetch("/v1/tts/providers");
  // ... error handling
  return res.json();
}

export async function synthesizeSpeech(
  text: string,
  opts?: { provider?: string; voice?: string; signal?: AbortSignal },
): Promise<{ audio: ArrayBuffer; fallback?: string }> {
  // POST /v1/audio/speech body: { input, provider, voice }
  // 讀取 response header X-TTS-Fallback / X-TTS-Fallback-Reason
  // 回傳 { audio, fallback } — fallback 有值時前端要顯示 toast
}
```

`fetchTtsProviders()` 直接打 `/v1/tts/providers`（跟 `/v1/audio/speech` 一樣不走 `/api` proxy）。

#### 6. Chat.tsx UI

在聊天輸入框上方加一行控制列：

```
[Provider ▾ 自動  ] [Voice ▾ hayley ]
```

- Provider 下拉：頁面載入時呼叫 `fetchTtsProviders()` 取得選項
- Voice 下拉：依選中 provider 的 `voices[]` 動態切換
  - 選「自動」時 voice 下拉隱藏（由 fallback chain 各自用預設）
- 選擇存 `localStorage`：`brain:tts-provider`, `brain:tts-voice`
- 頁面載入時從 localStorage 還原；若還原的 provider 不在清單中（已停用），自動 reset 為 `auto`
- 收到 fallback response 時顯示 toast 警告（例如「IndexTTS 無回應，已切換至 Edge TTS」）

### 不做的事

- 不做試聽按鈕
- 不做 voice 搜尋/篩選
- 不做後端持久化設定（純 localStorage）
- GCP/AWS/Edge 不做動態 voice 列表查詢

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/main.py` | 新增 `GET /v1/tts/providers`、`SpeechRequest` 加 `provider`、`create_speech` 讀 fallback 欄位寫 header |
| `backend/app/service.py` | 新增 `SynthesisOutput` wrapper、`synthesize()` 加 `provider` 參數、targeted + edge fallback 邏輯 |
| `frontend/admin/src/api.ts` | 新增 `TtsProvider` interface、`fetchTtsProviders()`、修改 `synthesizeSpeech()` 簽名與回傳 |
| `frontend/admin/src/pages/Chat.tsx` | 加 provider/voice 選擇器 UI、toast 警告、localStorage 讀寫 |

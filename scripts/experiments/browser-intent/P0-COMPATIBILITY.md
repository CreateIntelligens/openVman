# P0：瀏覽器小模型介面可行性查核

日期：2026-09-21。狀態：**結案，不進 P1**。介面查核與模型實測都已完成，未改任何
正式程式碼，也沒有讓任何人下載模型。
相關計畫與實驗入口見 [文件總覽](../../../docs/README.md#計畫與實驗)。

## 判準

SemIf 的 direct scoring 讀**指定答案 token 的 logits**（本 repo 的實作見
`scripts/experiments/semif/stability.py`，存的欄位是 `option_logits` 與
`probabilities`）。因此 P0 的通過條件不是「模型能不能在瀏覽器跑」，而是：

> **runtime 的 JS API 是否讓我們讀到指定候選 token 的分數？**

只能拿到生成文字的方案不算移植 SemIf，那是**生成式分類**，是另一種方法，
準確率與穩定性都得重新驗證，不能沿用既有結論。

## 相容性表

| Runtime | 模型支援 | 指定 token logits | 下載大小 | 運算後端 | 結論 |
|---|---|---|---|---|---|
| **WebLLM / MLC** | ✅ 官方 prebuilt 三種量化 | ✅ `processLogits(Float32Array)` 全 vocab | 447 MB (q4f16_1) | WebGPU，**無 fallback 記載** | **唯一可行** |
| WebLLM OpenAI 相容層 | ✅ | ❌ `top_logprobs` 上限 5 且只有 top-k；`logit_bias` 只寫不讀 | 同上 | 同上 | 不適用 |
| LiteRT-LM Web (Gemma 4 E2B) | ✅ `gemma-4-E2B-it-web.litertlm` | ❌ 輸出只有 `getTexts(): string[]` | **2.01 GB** | WebGPU 強制，無 fallback 記載 | 不可行 |
| transformers.js (ONNX) | ⚠️ 架構有列，但轉檔 issue #1574 仍開著，只有 `@next` | ⚠️ `logits_processor` 可觀察，但**未查到 `generate()` 回傳 scores** | ~646 MB（含用不到的 vision encoder） | WebGPU / WASM | 次選，今日不成熟 |
| wllama (GGUF) | ❌ 無官方支援清單 | ❌ 公開 API 無 logits 存取 | 563 MB (Q4_0) | WASM / WebGPU | 不可行 |

## 關鍵發現

### Gemma 4 E2B：介面直接排除

`@litert-lm/core@0.17.1` 的型別定義顯示整條輸出路徑終結於
`Responses.getTexts(): string[]`，沒有任何 logits／logprobs／分數回傳。

兩個名稱近似但**不是** logits API，別誤判：
- `GpuArtisanConfig.enable_decode_logits` — 輸入端設定開關
- `AdvancedSettings.num_logits_to_print_after_decode` — debug **列印**計數

兩者都不改變 `Responses` 的回傳內容，JS 端沒有讀取路徑。

另外它是 **early preview**（官方原文：`This is an early preview that supports
text-in / text-out running in WebGPU`），不是 GA。

### Web 下載大小：2.01 GB，不是 0.84 GB

交接文件正確警告過 0.84 GB 是 **Mobile 純文字版的載入記憶體**。實際 web 權重
（HF blobs API 位元組精確）：

    gemma-4-E2B-it-web.litertlm = 2,008,432,640 bytes = 2.01 GB

差距約 2.4 倍。Google 自己的文件從未載明 web 下載大小，效能表也**不含 web**。

### WebLLM：介面符合需求

已獨立向 `mlc-ai/web-llm` 的 `src/types.ts` 複查，確認為 exported interface：

```ts
export interface LogitProcessor {
  /**
   * Process logits after forward() and before sampling implicitly, happens on the CPU.
   * @param logits The logits right after forward().
   */
  processLogits: (logits: Float32Array) => Float32Array;
  processSampledToken: (token: number) => void;
  resetState: () => void;
}
```

拿到的是完整 vocab 的 `Float32Array`，可依 token index 取任意候選分數，
正是 SemIf 需要的形狀。另有 `forwardTokensAndSample(inputIds, isPrefill)`
可做非生成式 forward，官方 `examples/logit-processor/` 有可跑範例。

`Qwen3.5-0.8B-q4f16_1-MLC` 在官方 `prebuiltAppConfig` 內，
標示 `vram_required_MB: 1629.49`、`low_resource_required: true`。

## 查無（不要當成已確認）

- **無 WebGPU 時的行為**：WebLLM 與 LiteRT-LM 皆未記載 fallback 或錯誤路徑。
  視為硬性需求，但「無 fallback」本身也未經證實。
- **Gemma web 變體的裝置／RAM 需求**：未發布。
- **transformers.js 對 Qwen3.5 的穩定版支援**：轉檔 issue 仍開著，
  model card 要求 `@huggingface/transformers@next` 預發行版。
- **transformers.js `output_scores` / `return_dict_in_generate`**：JS 文件查無。
  只確認 processor 可在生成中觀察 logits，未確認 `generate()` 會回傳分數。
- **ONNX / WASM 路線的 RAM 需求**：未發布。
- **Qwen3.5-0.8B 的純文字變體**：查無。目前所有 runtime 的產物都含
  用不到的 vision encoder。

## P0 結論

**介面可行性通過，但只有一條路：WebLLM / MLC + Qwen3.5-0.8B。**

Gemma 4 E2B 以 P0 判準**不可行** —— 不是效能或大小問題，是 API 根本讀不到分數。

## 結論：不進 P1。介面可行，但模型不可靠

介面查核通過之後，先用現成的 `stability.py` 在**伺服器端**量了 Qwen3.5-0.8B
的順序穩定性——那是瀏覽器唯一跑得動的尺寸。這一步不必碰前端，也不必讓任何人
下載 447 MB，卻足以決定整條線該不該做。

同一組 32 題 × 24 種選項排列 × 3 次 = 2304 次評分：

| 指標 | Qwen3.5-4B | **Qwen3.5-0.8B** |
|---|---|---|
| 準確率 | 80.73% | **41.93%** |
| **順序敏感題數** | 21/32 | **32/32** |
| 任何排列都答對的題 | 11 | **0** |
| 最差／最好排列正確數 | 20／31 | 9／22 |
| 同輸入重跑翻轉 | 0 | 0 |
| p50／p95 | 374／409 ms | 292／350 ms |

**32 題全部只要換選項順序就改答案，沒有任何一題在 24 種排列下都答對。** 4B
至少還有 11 題穩固，0.8B 一題都沒有。那 41.93% 有多少是碰運氣已無追究意義。
換來的只有 22% 的延遲改善。

**這是模型層的問題，換到瀏覽器執行不會改善**——WebLLM 的 logits 介面再完美，
餵進去的還是同一個模型。

而它要挑戰的基線是現成的：

| | BGE 影子模式（現有） | 瀏覽器 Qwen3.5-0.8B |
|---|---|---|
| 下載 | 0（伺服器端既有模型） | 447 MB／使用者 |
| 延遲 | p50 約 54 ms | p50 約 292 ms |
| VRAM | 伺服器端 | 約 1.6 GB／使用者裝置 |
| 無 WebGPU 裝置 | 不受影響 | 無法運作，fallback 未記載 |
| 準確率 | 64 題 81.25% | 32 題 41.93%，且全部順序敏感 |

原始證據：[`scripts/experiments/semif/results/stability-0p8b/`](../semif/results/stability-0p8b/)
（metadata、逐筆 predictions、summary）。4B 的對照組在同層的 `stability/`，未覆寫。

## 若之後要重啟這條線

先問的不該是「哪個 runtime 能跑」，而是**「有沒有一個夠小、又對選項順序不敏感
的模型」**。前者已經有答案（WebLLM/MLC），後者目前沒有。

重測時直接沿用 `stability.py --model <新模型> --output <新目錄>`，門檻建議：
同輸入零翻轉（0.8B 與 4B 都已達成）**且**順序敏感題數顯著低於 21/32。

## 更正交接文件的一處數字

文件第 5 節 P2 寫「先用既有 **32 題**做回歸診斷」，但 `cases.jsonl` 實際有
**48 筆**（32 題是 routing 任務的子集，另含其他 task）。以實際檔案為準。

## 來源

- LiteRT-LM Web API：https://developers.google.com/edge/litert-lm/js
- `@litert-lm/core` registry：https://registry.npmjs.org/@litert-lm/core
- Gemma web 權重：https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/tree/main
- Gemma Terms：https://ai.google.dev/gemma/terms
- WebLLM `LogitProcessor`：https://github.com/mlc-ai/web-llm/blob/main/src/types.ts
- WebLLM 模型清單：https://github.com/mlc-ai/web-llm/blob/main/src/config.ts
- WebLLM logit-processor 範例：https://github.com/mlc-ai/web-llm/blob/main/examples/logit-processor/README.md
- MLC 權重：https://huggingface.co/mlc-ai/Qwen3.5-0.8B-q4f16_1-MLC/tree/main
- Qwen3.5-0.8B：https://huggingface.co/Qwen/Qwen3.5-0.8B
- ONNX 匯出：https://huggingface.co/onnx-community/Qwen3.5-0.8B-ONNX
- transformers.js logits_process：https://huggingface.co/docs/transformers.js/en/api/generation/logits_process
- transformers.js issue #1574：https://github.com/huggingface/transformers.js/issues/1574
- wllama：https://github.com/ngxson/wllama

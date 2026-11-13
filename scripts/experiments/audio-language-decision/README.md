# Gemini Decisions 台語前置判斷（2026-11-13）

目的：`POST /brain/internal/audio-language` 與 Live 的台語判斷原本只用 `gemini-3.5-flash-lite`，p50 約 1.8 秒。測 Gemini Decisions（`gemini-decision-1`）能不能更快回答「這句是不是台語」。

## 測試音檔

- 台語 20 句：台語連續劇真人錄音（`scripts/voice_e2e/cases/taigi-drama.json` 同一批，只在部署主機上有）。
- 華語 10 句、英西日韓各 5 句：Gemini TTS（`gemini-3.8-flash-tts`）合成。
- 全部轉成 16 kHz 單聲道 WAV。音檔不進 repo，`scores.json` 是每句的分數。

## 結果

直接問「是不是台語」不可靠：它把台灣腔、台灣情境也算進去，華語拿到 0.27～0.60，真人台語 0.24～0.91，兩邊重疊。選擇題（6 選 1、華語／台語二選一）取最高分也一樣，台語只對 11～13/20，常被聽成華語或韓語。

反過來問「是不是華語」就分得開：華語 0.82～0.93，真人台語除了一句 0.84 以外都在 0.61 以下。正式規則因此一次問五題是非題（華語、英、西、日、韓），規則在 `brain/api/memory/audio_language_decision.py` 的 `verdict`：

| 語言 | Decisions 自己下判斷 | 判錯 |
|---|---|---|
| 台語 | 12/20 | 0 |
| 華語 | 10/10 | 0 |
| 英語、西語 | 10/10 | 0 |
| 日語、韓語 | 1/10 | 0 |

其餘交給原本的模型。同一段音檔重問三次分數完全一樣。三題以上一起問，p50 0.43 秒、p90 0.52 秒。

## 限制

- 華語只有合成語音；帶台灣腔的真人華語會不會被拉低到 0.8 以下沒驗證，所以正式設定預設關閉。
- 真人台語只來自一部連續劇。

## 重跑

```bash
# 在 api 容器內（程式碼要含 memory/audio_language_decision.py）
python3 run.py <wav 目錄>...
```

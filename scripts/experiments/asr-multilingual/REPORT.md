# ASR 多語實測（中／英／西）

日期：2026-09-23。起因：鶴記會有中文、英文、西班牙文使用者。語音用 edge-tts 合成
（zh-TW-HsiaoChenNeural、en-US-JennyNeural、es-ES-ElviraNeural），不是真人錄音，
沒有口音與環境噪音，只能當下限參考。

測試句：
- 中：「請問你們的營業時間是幾點到幾點？另外我想預約這個星期六下午兩點，四個人，有兒童座椅嗎？」
- 西：「¿A qué hora abren los fines de semana? Quisiera reservar una mesa para cuatro personas el sábado.」

## 整段上傳（現行做法）

| 引擎 | 中文 | 西語（長句） | 速度 |
|---|---|---|---|
| SenseVoice | 正確 | 「케 va.」完全錯（短句是「Aka Ana.」） | 0.2 s |
| Breeze | 正確 | 後半句被翻成中文：「Quisiera reservar 一個桌子」 | 1.8 s |
| Xiaomi（正式環境目前的預設） | 正確 | 後半句變中文且混簡體 | 2.1 s |
| 舊 OpenAI（whisper-1、寫死 language=zh） | 簡體 | 被翻成中文且翻錯：「星期五凌晨幾點開門」 | 1–2 s |
| gpt-4o-mini-transcribe（不指定語言） | 繁體 | 正確 | 1.0–2.4 s |
| gpt-4o-transcribe | 簡體 | 正確 | 1.0–2.0 s |
| gemini-3.5-transcribe（language_codes zh-TW,en-US,es-ES） | 繁體 | 正確 | 3.2–4.0 s |

短句英文所有引擎都對。西語短句 Breeze、Xiaomi 對，句子一長就開始把西語改寫成中文。
故障切換只在引擎出錯時發生；轉成亂碼不算出錯，不會切到備援。

## 串流（WebSocket 邊講邊送）

| 引擎 | 結果時間 | 中間片段 | 中文 | 西語 |
|---|---|---|---|---|
| OpenAI Realtime 轉錄（gpt-4o-mini-transcribe，GA 介面、server_vad） | 每句停頓後約 0.3–0.4 s 定稿 | 有（一句十幾個 delta） | 繁體 | 正確 |
| gemini-3.5-transcribe-live（Live API，languageCodes） | 講完後 0.6–0.8 s | 這次沒收到，只有最終句 | 繁體 | 正確 |

OpenAI Realtime 的 beta 介面（`transcription_session.update` + `OpenAI-Beta` header）已停用，
要用 GA 的 `session.update`、`session.type=transcription`、`audio.input.format` 24 kHz PCM。
Gemini transcribe 支援 `custom_vocabulary`（最多 1000 詞），OpenAI 沒有對應功能。

## Gemini Live（對話模式）的轉錄

Live 對話的 `inputAudioTranscription` 帶 `languageCodes: ["zh-TW"]` 後中文出繁體，英、西不受影響
（不帶時中文是簡體；單數 `languageCode` 會被拒）。

## 結論

- 鶴記不能用 SenseVoice、Breeze、Xiaomi 處理西語。
- 整段上傳就用 gpt-4o-mini-transcribe；要低延遲就做串流，OpenAI（有即時字幕）或 Gemini
  （有自訂詞彙）二選一。
- Jev 只吃文字，不能在 ASR 之前判語言；但它對亂碼轉錄的信心很低（「Aka Ana.」0.1），
  可當「這段轉錄大概壞了」的訊號。文字的語言判斷 14 句對 12 句，約 200–290 ms。

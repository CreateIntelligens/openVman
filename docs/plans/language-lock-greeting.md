# 指定語言鎖定、依語言開場白與聲音

狀態：Draft（2026-11-25）

## 背景

鶴記（VH-445）要中、英、西三語的虛擬人：對話一開始指定語言，Mr. Walter 用那個語言開場，之後都用那個語言回答，知識也只查那個語言的內容。

現況（2026-11-25 查）：

- `ChatRequest.preferred_language`（zh／en／es／nan／ja／ko）只是提示。使用者這句話看得出語言，或明講要哪種語言時，都照使用者的（`brain/api/core/turn_decisions.py` `resolve_retrieval_language`、`prompt_templates.py` 的語言規則），而且每輪都要帶，不存進 session。
- 檢索語言是「優先」，不是只查該語言。
- SDK `ask()`、官方前台、backend WebSocket 都不能帶語言，只有後台的對話測試頁能帶。
- 沒有可設定的開場白，只有攝影機偵測到訪客時，用寫死的中文提示讓模型自己生一句招呼（`backend/app/gateway/plugins/vision_events.py`）。
- 人設只有 `avatar_char_id` 這個中繼資料，沒有語言或 TTS 聲音的欄位。

## 決定

- 指定語言就鎖死：使用者改講別種語言，仍用指定的語言回答（使用者 2026-11-25 拍板）。
- 檢索只查指定語言的知識：QA 只查該語言分類下的題目；一般文件只查標成該語言的文件。查不到不改查別的語言。
- 一個人設搭配多語，不拆成三個人設：人設內容只維護一份，開場白和聲音依語言各設一份。

## 要做的

1. Brain（第一階段完成）
   - `ChatRequest` 加 `language`（只收 `zh`、`en`、`es`、`ja`、`ko`，不收台語）。有帶就鎖定：回覆語言、檢索語言都用它，跳過 `requested_response_language` 與偵測。`preferred_language` 維持原本的提示語意，兩個都帶時以 `language` 為準。
   - 檢索依 `language` 過濾：QA 只看該語言分類，文件只看該語言的文件。
   - 人設新增開場白：每個語言一段文字，存在人設資料夾的中繼資料裡。新增 `GET /brain/personas/greeting?persona_id=&project_id=&language=en`，沒設定該語言時回 404；設定用 `GET/PUT /brain/personas/language-settings`。
   - 人設新增「語言對應 TTS 聲音」：`{ "en": "<voice_id>", … }`。
2. Backend
   - `/api/v1/chat/stream` 照轉 `language`（現在是原樣代理）。（第一階段完成：測試證明原樣轉送；`/personas/language-settings`、`/personas/greeting` 已加進代理，需登入）
   - WebSocket 的 `capabilities` 加 `language`，Live 與文字回合都帶進 Brain。
   - TTS：請求有 `language`、而人設有對應聲音時用那個聲音，否則照現在的預設。
3. 前台與 SDK
   - SDK `init` 加 `language`，之後每次 `ask()` 都帶；新增 `greet()`：取開場白並用該語言的聲音念出來。（第一階段完成）
   - 官方前台：網址參數或語言選擇器選定語言後，自動播開場白；之後的對話都帶 `language`。
4. 後台
   - 人設頁加「開場白」區塊（每個語言一欄）與「各語言聲音」設定。
   - 對話測試頁可以選鎖定語言。
5. 協定與文件
   - 更新 `contracts/schemas/v1/` 後重新產生契約；更新 `docs/specs/`、`brain/README.md`、整合指南、`CHANGELOG.md`。

## 還沒定的

- 台語不納入 `language`（台語轉文字是中文字，鎖定規則跟其他語言不同），之後有需要再說。
- 鶴記 Kiosk 與官網各用哪個前台、能不能帶 `language`，等 PM 回覆（VH-445）。
- 網站嵌入金鑰可以呼叫 `GET /api/v1/personas/greeting`（2026-11-25 使用者決定放行）：專案由代理依金鑰綁定，Brain 以 `X-OpenVMan-Project-ID` 為準，網址沒帶專案也不會退回 default。
- 西文 TTS 用哪個聲音，等 PM 回覆。

## 驗收

在鶴記dev 以 zh、en、es 各跑一次：開場白跟鶴記提供的文件一致、聲音是該語言設定的聲音、用別的語言提問仍以鎖定語言回答，且答案只引用該語言的知識。

## 追加：人設的聯絡圖片（2026-11-25）

鶴記 Kiosk 要每題都放 EVAK QR code，同時保留 QA 的產品圖；一題只有一個圖片欄放不下兩張。改成人設設定一張聯絡圖片（`PUT /personas/contact-image`），每則回覆以 `contact_image_id` 另外帶出。答不出來時回應本來就有 `no_answer: true`，加上聯絡圖片後前台不必另外判斷就有 QR 可顯示。官方前台會在回覆氣泡顯示這張圖（2026-11-25 上線，鶴記 kiosk 人設已設 EVAK QR）；SDK 還沒顯示，整合方從回應的 `contact_image_id` 自行顯示。

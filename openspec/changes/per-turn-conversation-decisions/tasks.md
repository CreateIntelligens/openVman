# Tasks

## 1. 合併決策資料與政策

- [x] 1.1 建立 `TurnDecision`／`TurnPolicy` 與固定 typed questions 清單；以複合需求、無效 choice、缺欄位與低信心案例驗證三種檢索需求可同時成立及逐用途棄權。
- [x] 1.2 建立有界 evidence builder，優先保留原始本輪訊息、最近 user/assistant 歷史及允許的語言／工具代碼；測試 slash 原句、引用、超長歷史與排除 system/tool/秘密／帳號資料。
- [x] 1.3 實作純 policy resolver 與 validated confidence／margin 設定；驗證寒暄可略過強制 knowledge、事實／追問／不確定恢復既有政策、client metadata 不可偽造 policy。
- [x] 1.4 在 `brain/README.md` 記錄 batch IDs、輸出代碼、門檻與外送 evidence 契約；逐項對照 schema 與 privacy 測試確認文件一致。

## 2. Broker budget 與取消

- [x] 2.1 為共用 broker 增加本用途的 optional per-hop cap，保留既有 callers 的 timeout 預設；以慢速回應／中途故障測試 shared deadline 和後續 hop 機會。
- [x] 2.2 建立 HTTP／async Live 都能使用的 cancel handle，取消 propagation 到 provider HTTP future；驗證取消 worker wrapper 後沒有仍在等待的網路請求或 late-result application。
- [x] 2.3 加入 turn-decision 總開關、分組開關與 budget／hop-cap 環境設定；測試非法門檻、feature disabled、全部停用 provider 與初次 config failure。
- [x] 2.4 在 `.env.example` 與 Brain 詳細文件記錄預設、shared budget／per-hop 關係和 baseline 行為；以設定測試確認文件值。

## 3. HTTP retrieval 路徑

- [x] 3.1 在 `chat_service.prepare_generation()` 讀取歷史後、prompt／recall 前執行 batch，將結果綁定 server-owned turn/revision；驗證一般 user、slash、ephemeral media、tool/control 入口及 generation retry 呼叫數。
- [x] 3.2 將政策傳入 prompt 和 agent loop，同步處理取消強制 knowledge 與 unconditional 提示；驗證寒暄沒有 mandatory RAG，LLM 仍可補查，必要 reads 不會因第一輪純文字回應而消失。
- [x] 3.3 補齊 positive web/knowledge 的合法第一輪 read requests，保留 fast mode、registry 與專案邊界；以多來源並行、工具停用和未提供工具案例驗證可執行清單。
- [x] 3.4 將 needs_memory 接入 auto recall，保留 session/config 開關與已完成讀取的 satisfied 訊號；測試跳過無關召回、召回停用、memory write gate 仍獨立，以及 batch outage 後使用 LLM/formatted 退路。
- [x] 3.5 更新 `docs/specs/03_BRAIN_SPEC.md` 的一般回合、強制工具與 recall 流程；與 pipeline 測試對照，確認 feature disabled 仍走現有路徑。

## 4. 多語言與語氣

- [x] 4.1 實作 input languages、mixed、dominant、requested reply 和 resolved reply language 的分離解析；測試中英混用、中文引用西文、品牌／型號、明確切換與未支援語言。
- [x] 4.2 將當輪 retrieval language 傳入 HTTP knowledge tools，將 reply language 傳入 prompt、reply length 與 retry 規則；測試台語 ASR → 中文文字 → 英文回覆，確保原 ASR evidence 與 TTS 設定不被偽造。
- [x] 4.3 讓 session 訊息標籤重用可靠 input language，避免同則訊息再次跑 legacy language decision；測試標籤未被 reply language 覆寫，以及失敗時只採本地標籤。
- [x] 4.4 實作固定 tone-to-delivery 映射；測試困惑／挫折／急迫的 hints、低信心 persona、使用者格式與長度優先，並驗證 tone 不進 DB、usage raw、日誌或長期記憶。
- [x] 4.5 更新 Brain README 與語言規格，說明 input/retrieval/reply 語言順序、ASR 參考和當輪 tone 邊界；以代表案例確認文件預期輸出。

## 5. Gemini Live 正式文字回合

- [x] 5.1 在 `send_text_turn()` 執行相同 batch 與每輪 context，使用 async wrapper 與 cancel handle；以文字／Backend ASR 定稿、連續語言切換與 partial/raw-audio bypass 測試驗證 listener 保持可處理事件；Gemini 內部 raw-PCM transcription 在當輪生成啟動後只套用後續 retrieval policy。
- [x] 5.2 為有效 policy 實作 bounded turn envelope 與必要的合法 read-only 預取，標記 satisfied／untrusted evidence；測試 knowledge+web+memory 複合需求、前文指代與不能由 user text 偽造 envelope 控制。
- [x] 5.3 將 retrieval language 與必要 read policy 接入 Live tool executor；測試每輪取消／revision supersession／兩個 project，確保舊語言、tone、late prefetch 結果不影響下一輪。
- [x] 5.4 更新 `brain/README.md` 與 Live 詳細文件，記錄 finalized-text scope、envelope、無決策退路與 session setup 限制；驗證 feature disabled 的 Live payload／工具行為仍符合原有契約。

## 6. 獨立案例、運行量測與交付文件

- [ ] 6.1 建立至少 60 個與 prompt 開發集分離的人工標籤案例及執行腳本；驗證事實／追問錯誤 knowledge skip 為 0、明確支援語言與權限案例全通過、其餘支援語言至少 95%，並記錄允許的 tone hints。
- [x] 6.2 加入 `decision_turn` usage 用途、固定維度延遲／skip/fallback 計量及當輪 unavailable context；測試 raw text／tone label 不外洩、故障時同一回合不重試 unavailable chain。
- [ ] 6.3 以相同案例比較 baseline 與 enabled 路徑的 tool counts、整輪時間與答案證據覆蓋；輸出實測報告並明確標示未量測或 provider 差異。
- [x] 6.4 更新 root README、Brain README、詳細規格與 `CHANGELOG.md [Unreleased]`；交付同事可依序操作的寒暄、產品追問、多語言、語氣與全部 hop outage 驗收清單。

## 7. 整合驗收與 review

- [x] 7.1 跑跨 HTTP／Live 的 mocked fallback matrix：Clef 主成功、主失敗後備援、Jev/OpenAI 接手、全部失敗、全部停用、missing key、config failure；驗證每個情況的實際 reads、reply language 和正常 stub reply。
- [x] 7.2 執行相關 focused tests、Brain 非 integration suite、受影響的 Backend 測試、型別檢查、OpenSpec strict validation 與 git diff whitespace 檢查，記錄結果及範圍限制。
- [x] 7.3 完成獨立 code review，重點檢查工具權限、當輪 evidence、取消／deadline、低信心與 outage 退路；修正重要發現後重跑受影響測試並記錄複查結果。

## Workflow follow-up

- 驗收及 review 完成後，依使用者指示封存本 change；前置供應商 change 保持獨立的完成紀錄。


## 8. 前台決策 Debug（2026-10-08）

- [x] 8.1 加入明確選用的 HTTP／Live 診斷傳輸；只回固定 IDs、typed 答案與實際 provider／policy，排除 evidence 並驗證 delivery／history 不保存診斷。
- [x] 8.2 加入虛擬人舞台 Debug 開關與 14 項判讀面板，顯示情緒、信心／成立機率、門檻結果、fallback 和實際策略；清除舊回合／專案／session 資料。
- [x] 8.3 更新 protocol schemas 與 generated contracts、日期版 CHANGELOG／README／詳細規格；以實際桌面／手機瀏覽器驗證顯示、清除、fallback、opt-out 與排版。
- [x] 8.4 完成獨立 code review 並處理 findings，執行受影響前後端測試、build、contract check 與 diff check。

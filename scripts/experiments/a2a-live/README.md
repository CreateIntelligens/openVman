# A2A 真實 Hub 往返驗證

日期：2026-09-20。使用者明確授權建立隔離測試圈及暫時 Agent。結果：[result.json](result.json)。

**成功完成一筆真實往返，約 9.55 秒。** 測試訊息與回覆只包含連線測試要求及隨機識別碼；沒有送出正式用戶內容。

## 已驗證鏈路

1. 以隨機私有圈金鑰向 https://a2a.david888.com 註冊兩個暫時身分，確認同圈、非 public，並能互相發現。
2. 在既有 Backend 容器的獨立程序啟動只綁定 loopback 的 FastAPI facade，使用真正 internal_routes router、A2AClient 及內部驗證 token。僅該程序啟用 A2A 並指定 sender bridge；正式 Backend 設定與程序未更動。
3. 從目前 Brain skill 程式呼叫 a2a_send_task，經真正 HTTP facade → 真實 Hub，取得 taskId 與 QUEUED 回應。
4. 接收端使用既有 A2ABridgeDaemon._stream_inbox，透過真實 SSE 收到完全相同的訊息，先寫入 SQLite 工作佇列，再 ACK。
5. 執行真正 bridge 工作處理，呼叫已部署 Brain 的 /brain/chat 產生回覆，工作記錄變成 COMPLETED，再透過 Hub 派回 sender。
6. sender 經 SSE 收到 A2A_PONG a2a-smoke-60cdc55af1e6，寫入佇列並 ACK。此為終止測試回覆，不再觸發互相回信。

主要 taskId：2166e807-561c-4d20-a85e-42be3652784a；回覆 taskId：b695ff73-351b-4c5c-905e-f47eccbd30ab。Hub sequence 分別為 361、362。

## 邊界與清理

這不是正式 Backend listener 已啟用的證明：正式 A2A_ENABLED 仍是 false，沒有重啟或部署服務。隔離程序將 leader 身分明確指定；Redis leader election、斷線重連及程序重啟恢復未在此測試涵蓋。兩個身分皆由測試程序管理，並非另一套獨立部署的第三方 Agent；接收端使用現有真實 Brain，沒有固定字串回覆替代模型。

首次測試腳本誤用了不存在的 _listen_sse 方法，在發送任務前失敗；修正為 _stream_inbox 後成功。首次已註冊的兩個身分，以及成功輪的兩個身分，共四筆 Hub 測試身分留存。未找到已確認的自行撤銷端點，因此不宣稱已刪除 Hub 註冊；本機所有 listener 均停止、暫時憑證及私有圈金鑰已刪除，不再更新 presence，遠端租期到期後會轉為離線。

測試會在 Brain 留下一筆帶測試識別碼的對話；保留作為實際模型往返證據。result.json 不包含金鑰或 token。若要重測，應重新建立隔離私有圈與暫時身分；不要重用公開圈，也不要把本次成功解讀成可以未經授權向其他 Agent 派工。

後續 simplify 僅整理 A2A 輸入驗證與測試；result.json 的 skill_sha256 保留本次真實往返時的來源 hash，不代表整理後檔案。此次整理使用容器內回歸及 loopback 測試，沒有再向真實 Hub 註冊或派工。

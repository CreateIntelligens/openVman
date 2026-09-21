# README 規劃與功能摘要快照

> 於 2026-09-21 整理文件時從根 README 移入。以下保留原文，包含當時的待辦與完成宣稱；未重新核對，不代表目前部署或驗收狀態。

## 七、待撰寫文件規劃

| 文件 | 預計內容 |
|------|----------|
| `05_SECURITY.md` | WebSocket JWT 認證流程 · API Key 管理 · Kiosk 設備白名單 · TLS/WSS 設定 · Prompt Injection 防護細節 |
| `06_ASSET_PIPELINE.md` | 從照片/影片生成 idle.mp4 的 SOP · 6 張嘴型 Sprite 的製作方法 · manifest.json 的校準流程 · 素材品質檢查清單 |
| `07_MONITORING.md` | Grafana Dashboard 設計 · 告警規則 (Alertmanager) · SLA 定義 (可用性 99.9%) · 日誌查詢範例 (ELK/Loki) |

---

## 八、結論

**核心架構完整度高**，四份 Spec 共 41 個章節，覆蓋了從通訊協定到認知系統的完整技術棧。

**架構亮點**：
- ✅ 感官 / 神經 / 靈魂 三層解耦，職責零重疊 (Frontend 獨立運作)
- ✅ **獨立網關層 (Gateway)**：前置消化多模態素材與非同步任務 (BullMQ)，保持大腦與核心後端輕量、穩定。
- ✅ **系統外掛擴充 (Gateway Plugins)**：原生支援 Camera Live 與 Web Crawler，強化視覺感知與即時爬網能力。
- ✅ LLM → Chunker → TTS → WebSocket 串流管線，延遲最小化
- ✅ **設備自適應對嘴 (Device-Adaptive Lip-Sync)**：高階設備 → Wav2Lip，低階設備 → DINet (39 Mflops)
- ✅ VideoSync 唯一時鐘源 + 徑向漸變羽化，杜絕嘴型漂移與生硬邊界
- ✅ **Knowledge Base Admin Panel**：整合遞迴式檔案探索器與雙視窗 Markdown 編輯器，支援 LanceDB 同步狀態展示。
- ✅ **Admin Web Light Mode**：整合專屬風格系統，支援深淺色模式切換與持久化儲存。
- ✅ **RAG v2 架構**：整合 LanceDB Hybrid Search (BM25) + pdf-inspector / Docling / AnyDoc 文件 ingestion 管線
- ✅ **Brain Skills 模組化擴充系統**：支援動態載入外部技能工具，技能註冊表在執行期同步（無須重啟）
- ✅ **Forced Tool Call Routing**：可針對單次請求強制指定技能調用路徑，結合動態 skill registry 讓新註冊的技能立即可用
- ✅ **Direct Chat Route**：純對話訊息跳過 tool-instruction 組裝，降低 prompt 體積與延遲
- ✅ **Chat Action Request Flow**：Brain 以結構化 action proposal 形式回傳工具調用請求，Admin UI 以 ActionRequestCard 讓操作者逐項審批
- ✅ **Knowledge Graph (graphify)**：內建 graphify 技能與 graph HTTP endpoints，Admin 知識庫新增 Graph 視覺化分頁
- ✅ **Unified Admin Navigation**：以 NavigationContext 集中管理路由/分頁狀態，整合 AppSidebar、ChatSidebar 與各頁面；設計 token 改以 RGB channel 暴露，完整支援 Tailwind opacity modifier
- ✅ **LLM Failover (DR Mode)**：支援跨 Provider (Gemini/OpenAI/Groq) 自動故障轉移
- ✅ **2md 即時網路工具**：`search_web(query)` 搜尋公開網路，`read_web_page(url)` 讀取網頁、PDF 與支援文件；依主力／兩級 fallback 自動降級
- ✅ **2md 驚群防護**：固定 `TWO_MD_BASE_URLS` 順序，採 sequential fallback、共用 deadline、full-jitter、single-flight 與可選 Redis circuit/half-open lease
- ✅ **David888 Wiki 分享**：長篇報告可透過 `publish_wiki` 發布，完成後只回傳公開 `shareUrl`
- ✅ **外部工具開關**：`URL2MD_SEARCH_ENABLED`、`URL2MD_READ_ENABLED`、`WIKI_PUBLISH_ENABLED` 預設為 `true`，可個別停用並在重啟後套用
- ✅ **動態 Gemini 模型探索與容錯鏈 (Dynamic Fallback Chain)**：支援透過 Gemini SDK 自動探索所有可用生成模型並進行 Pro -> Flash -> Flash-Lite 語意化排序，具備 10 分鐘快取與靜態安全網降級機制
- ✅ 完整的錯誤處理、斷線重連、優雅關機機制
- ✅ Token 預算管理 + 安全防護 (Guardrails)

**後續方向**：
- 📋 撰寫 `04~07` 補充文件（部署 / 安全 / 素材 / 監控）
- 📋 擴充更多專業領域的 Brain Skills
- 📋 進入實作階段

---


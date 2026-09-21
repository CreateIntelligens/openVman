# 歷史資料索引

這裡保存早期設計、一次性工作紀錄與研究摘錄。歸檔是分類整理，不代表計畫已完成或取消；原文的 Draft、Done、DEPRECATED 與勾選狀態均保留。操作請從 [文件總覽](../README.md) 查找。

## 早期開發規劃

[八週 MVP 規劃](initial-planning/08_PROJECT_PLAN_2MONTH.md)與以下 TASK 文件保留當時的 Issue、分支、設計及驗收方式，不代表目前實作或排程。TASK 編號沿用原文，原目錄沒有 TASK-12，不補造文件。

| 任務 | 原始狀態 |
|------|----------|
| [TASK-01: Backend Message Envelope and Trace Context](initial-planning/TASK-01-backend-message-envelope-and-trace-context.md) | Draft |
| [TASK-02: Backend Session State Machine and Inflight Guard](initial-planning/TASK-02-backend-session-state-machine-and-inflight-guard.md) | Done |
| [TASK-03: Backend Interrupt and Unified Error Bridge](initial-planning/TASK-03-backend-interrupt-and-unified-error-bridge.md) | Done |
| [TASK-04: Shared Protocol Schema Definitions and Validators](initial-planning/TASK-04-core-protocol-event-schemas.md) | Done |
| [TASK-05: Generate Shared TS and Python Protocol Types](initial-planning/TASK-05-generated-shared-protocol-contracts.md) | Draft |
| [TASK-06: Protocol Handshake and Compatibility Checks](initial-planning/TASK-06-protocol-handshake.md) | Draft |
| [TASK-07: Frontend Audio Queue and Chunk Playback Controller](initial-planning/TASK-07-frontend-audio-queue-and-chunk-playback.md) | Draft |
| [TASK-08: Adaptive Frontend Rendering (Wav2Lip / DINet / WebGL)](initial-planning/TASK-08-adaptive-frontend-rendering.md) | Draft |
| [TASK-09: Frontend Reconnect, Error, and Recovery UX](initial-planning/TASK-09-frontend-reconnect-error-recovery-ux.md) | Draft |
| [TASK-10: IndexTTS2 Service Bootstrap and Inference API](initial-planning/TASK-10-indextts2-service-bootstrap-and-inference-api.md) | Draft；DEPRECATED |
| [TASK-11: zh-TW Speaker Profile and Pronunciation Override Support](initial-planning/TASK-11-zh-tw-speaker-profile-and-pronunciation-override-support.md) | Draft；DEPRECATED |
| [TASK-13: TTS Node Health Scoring and Primary-Secondary Failover](initial-planning/TASK-13-tts-node-health-scoring-and-primary-secondary-failover.md) | Draft |
| [TASK-14: AWS Fallback Adapter for TTS Router](initial-planning/TASK-14-aws-fallback-adapter-for-tts-router.md) | Draft |
| [TASK-15: GCP Fallback Adapter and Fallback Metrics](initial-planning/TASK-15-gcp-fallback-adapter-and-fallback-metrics.md) | Draft |
| [TASK-16: Brain Message Normalization and Enrichment Stage](initial-planning/TASK-16-brain-message-normalization.md) | Draft |
| [TASK-17: Brain Route-Guard-Assemble Pipeline](initial-planning/TASK-17-brain-route-guard-assemble.md) | Done |
| [TASK-18: Brain HTTP-SSE Interface with Trace Propagation](initial-planning/TASK-18-brain-http-sse-interface.md) | Draft |
| [TASK-19: Markdown Chunking and LanceDB Indexing Pipeline](initial-planning/TASK-19-markdown-chunking-and-lancedb-indexing-pipeline.md) | Draft |
| [TASK-20: Retrieval and Reranking Service for Brain Context](initial-planning/TASK-20-retrieval-and-reranking-service-for-brain-context.md) | Draft |
| [TASK-21: Daily Memory Writeback and Re-index Hooks](initial-planning/TASK-21-daily-memory-writeback-and-re-index-hooks.md) | Draft |
| [TASK-22: LLM Key Pool Manager and Quota-Aware Routing](initial-planning/TASK-22-llm-key-pool-manager-and-quota-aware-routing.md) | Draft |
| [TASK-23: Model and Provider Fallback Chain Execution](initial-planning/TASK-23-model-and-provider-fallback-chain-execution.md) | Draft |
| [TASK-24: Routing Observability and Circuit-Breaker Metrics](initial-planning/TASK-24-routing-observability-and-circuit-breaker-metrics.md) | Draft |
| [TASK-25: Tool Schema Registry and Execution Bridge](initial-planning/TASK-25-tool-schema-registry.md) | Draft |
| [TASK-26: Mock FAQ and Order-Query Business Tool Flow](initial-planning/TASK-26-mock-business-tools.md) | Draft |
| [TASK-27: Tool Error Handling and Reinjection into Stream](initial-planning/TASK-27-tool-error-handling-and-reinjection.md) | Draft |

## 一次性筆記

- [舊 Live Pipeline 驗證草稿](notes/VERIFY_LIVE_PIPELINE.md)：操作入口與延遲目標未符合現況，不作為驗收標準。

- [Live Pipeline 文件對齊待辦](notes/ALIGNMENT_NOTES_LIVE_PIPELINE.md)：當時要求補齊的內容，未在此次整理中驗收。
- [README 規劃與摘要快照](notes/readme-planning-snapshot.md)：從入口移出的舊待辦與功能宣稱。

## 技術研究

- [DINet 與虛擬人技術比較](research/dinet.md)
- [2026-03-23 虛擬人技術評估](research/vman20260323.md)

研究內容可能過時或重複，保留作為選型背景，不等於目前採用方案。

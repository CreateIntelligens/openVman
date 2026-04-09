# Graph Report - .  (2026-04-09)

## Corpus Check
- 361 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3941 nodes · 7221 edges · 126 communities detected
- Extraction: 54% EXTRACTED · 46% INFERRED · 0% AMBIGUOUS · INFERRED: 3338 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `TTSRouterConfig` - 88 edges
2. `SynthesizeRequest` - 77 edges
3. `NormalizedTTSResult` - 64 edges
4. `SessionStore` - 49 edges
5. `ProtocolValidationError` - 46 edges
6. `TTSRouterService` - 37 edges
7. `IngestionResult` - 36 edges
8. `Conv1d` - 35 edges
9. `Linear` - 31 edges
10. `BatchNorm1d` - 31 edges

## Surprising Connections (you probably didn't know these)
- `Generated shared protocol contracts.` --uses--> `GeminiLiveSession`  [INFERRED]
  contracts/generated/python/openvman_contracts/__init__.py → brain/api/live/gemini_live.py
- `JsonTransport` --uses--> `TTSRouterConfig`  [INFERRED]
  brain/api/live/gemini_live.py → backend/app/config.py
- `GeminiLiveWebSocketTransport` --uses--> `TTSRouterConfig`  [INFERRED]
  brain/api/live/gemini_live.py → backend/app/config.py
- `Brain-owned Gemini Live session manager.` --uses--> `TTSRouterConfig`  [INFERRED]
  brain/api/live/gemini_live.py → backend/app/config.py
- `JsonTransport` --uses--> `Session`  [INFERRED]
  brain/api/live/gemini_live.py → backend/app/session_manager.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (148): AWSPollyAdapter, _locale_to_language_code(), AWS Polly adapter for TTS routing., Synthesize speech via AWS Polly and return a NormalizedTTSResult., Call Polly and return normalized result.          Raises on failure — the caller, Map a locale hint to an AWS Polly LanguageCode., NormalizedTTSResult, ProviderAdapter (+140 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (83): dispatchSseEvent(), parseSsePayload(), processSseBuffer(), streamChat(), apiUrl(), buildUrl(), de_tokenized_by_CJK_char(), fetchJson() (+75 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (130): AgentLoopResult, _append_tool_turns(), _assistant_tool_message(), _execute_tool_call(), prepare_agent_reply(), PreparedAgentReply, LLM tool loop orchestration., Raised when the tool phase fails (e.g. max rounds exceeded).      Carries the pa (+122 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (88): Activation1d, Activation1d, forward(), FusedAntiAliasActivation, Assumes filter size 12, replication padding on upsampling/downsampling, and logs, AMPBlock1, AMPBlock2, BigVGAN (+80 more)

### Community 4 - "Community 4"
Cohesion: 0.02
Nodes (122): BaseSettings, blocked_domain_set(), BrainSettings, EmbeddingBackend, get_settings(), get_tts_config(), 大腦層集中設定 — 從 .env 讀取所有環境變數, Resolved embedding backend contract for one version alias. (+114 more)

### Community 5 - "Community 5"
Cohesion: 0.02
Nodes (112): _clean_markdown(), CrawlResult, _extract_markdown_title(), fetch_page(), _is_junk_content(), _is_noise_line(), _parse_provider_response(), Thin adapter for web content extraction via configurable provider. (+104 more)

### Community 6 - "Community 6"
Cohesion: 0.02
Nodes (89): add_memory(), append_session_message(), archive_session_turn(), build_memory_record(), delete_memory(), delete_session_for_project(), get_or_create_session(), get_session_store() (+81 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (100): BaseModel, GenerationContext, _background_reindex(), _background_rename_document(), _build_openapi_schema(), _cached_speech_response(), cancel_task(), chat() (+92 more)

### Community 8 - "Community 8"
Cohesion: 0.03
Nodes (60): ApiToolPlugin, ApiTool plugin — YAML registry + rate limiting + HTTP calls., Build auth headers based on API definition., Replace ${ENV_VAR} patterns with environment variable values., Executes HTTP calls against a YAML-defined API registry with rate limiting., Load API registry from YAML file., Sliding window rate limiter. Returns True if request is allowed., Execute an API call.          params:             api_id: str — which API from r (+52 more)

### Community 9 - "Community 9"
Cohesion: 0.05
Nodes (64): MultiHeadedAttention, Compute scaled dot product attention.          Args:             query (torch.Te, Multi-Head Attention layer with relative position encoding.     Paper: https://a, Construct an RelPositionMultiHeadedAttention object., Compute relative positinal encoding.         Args:             x (torch.Tensor):, Compute 'Scaled Dot Product Attention' with rel. positional encoding.         Ar, Multi-Head Attention layer.      Args:         n_head (int): The number of heads, Construct an MultiHeadedAttention object. (+56 more)

### Community 10 - "Community 10"
Cohesion: 0.03
Nodes (19): DinetStrategy, applyROISimple(), applyROIWithBlend(), createFeatheredMask(), createWav2LipModel(), detectAllCapabilities(), detectAndroid(), detectCPUCores() (+11 more)

### Community 11 - "Community 11"
Cohesion: 0.04
Nodes (40): AbsolutePositionalEmbedding, AlibiPositionalBias, always, apply_rotary_pos_emb(), Attention, AttentionLayers, cast_tuple(), ContinuousTransformerWrapper (+32 more)

### Community 12 - "Community 12"
Cohesion: 0.05
Nodes (33): AttentionBlock, GroupNorm32, normalization(), QKVAttentionLegacy, Zero out the parameters of a module and return it., Make a standard normalization layer.      :param channels: number of input chann, A module which performs QKV attention. Matches legacy QKVAttention + input/outpu, Apply QKV attention.          :param qkv: an [N x (H * 3 * C) x T] tensor of Qs, (+25 more)

### Community 13 - "Community 13"
Cohesion: 0.05
Nodes (61): ClientAudioChunkEvent, ClientAudioEndEvent, ClientInitEvent, ClientInterruptEvent, GeneratedProtocolModel, Generated by contracts/scripts/generate_protocol_contracts.py. Do not edit manua, ServerErrorEvent, ServerInitAckEvent (+53 more)

### Community 14 - "Community 14"
Cohesion: 0.03
Nodes (15): ASRService, AudioPlaybackService, AudioStreamer, clampFloatToInt16(), float32ToInt16(), pcm16ToBase64(), resampleFloat32ToPcm16(), FakeAudioContext (+7 more)

### Community 15 - "Community 15"
Cohesion: 0.05
Nodes (28): GeminiLivePipeline, GeminiLiveSession, GeminiLiveWebSocketTransport, _parse_sample_rate(), _pcm_to_wav(), Brain-owned Gemini Live session manager., Minimal JSON transport for Gemini Live's raw websocket API., Minimal JSON transport for Gemini Live's raw websocket API. (+20 more)

### Community 16 - "Community 16"
Cohesion: 0.07
Nodes (47): Mock business data for FAQ and order tools.  This module contains hardcoded data, get_skill_manager(), Skill manager for discovering, loading, and managing brain skills., Dynamically load handlers from the skill's main.py., Return a loaded skill or raise ValueError., Retrieve a loaded skill by ID., List all loaded skills., Toggle a skill between enabled and disabled. (+39 more)

### Community 17 - "Community 17"
Cohesion: 0.04
Nodes (38): _already_ran_today(), _build_status_config(), _compute_next_run(), CronSpec, _discover_project_ids(), _dreams_dir(), _extract_phase_stats(), get_candidates_preview() (+30 more)

### Community 18 - "Community 18"
Cohesion: 0.03
Nodes (24): BaseProcessingInfo, GPT2Model, GPT2TTSModel, LearnedPositionEmbeddings, GPT2Model, GPT2TTSModel, LearnedPositionEmbeddings, # NOTE: "c_attn.bias" should not be skipped. (+16 more)

### Community 19 - "Community 19"
Cohesion: 0.04
Nodes (19): FeatureExtractor, MelSpectrogramFeatures, Extract features from the given audio.          Args:             audio (Tensor), Base class for feature extractors., 将 jqx 的韵母为 u/ü 的拼音转换为 v         如：ju -> jv , que -> qve, xün -> xvn, 替换人名为占位符 <n_a>、 <n_b>, ...         例如：克里斯托弗·诺兰 -> <n_a>, 恢复人名为原来的文字         例如：<n_a> -> original_name_list[0], 替换拼音声调为占位符 <pinyin_a>, <pinyin_b>, ...         例如：xuan4 -> <pinyin_a> (+11 more)

### Community 20 - "Community 20"
Cohesion: 0.05
Nodes (51): build_fallback_chain(), Bounded fallback chain for LLM provider/model routing., A single hop in the fallback chain., Build an ordered list of route hops from the configured fallback chain.      Eac, RouteHop, classify_failure(), KeyPoolManager, KeyState (+43 more)

### Community 21 - "Community 21"
Cohesion: 0.05
Nodes (48): enqueue_job(), EnqueueResult, _get_arq_pool(), push_to_dlq(), Arq-based job queue with sync fallback., Push a failed job entry to the dead-letter queue in Redis., _build_entry(), _ensure_writer() (+40 more)

### Community 22 - "Community 22"
Cohesion: 0.05
Nodes (31): _load_indexer(), TASK-19: Tests for heading-aware markdown chunking and indexing pipeline., Chunks from different headings must not be merged., A heading block exceeding char limit gets split into multiple chunks., Every chunk must include heading_path, chunk_index, and char_count., Nested headings produce correct heading_path hierarchy., Plain text without headings should still be chunked., Image markdown should be removed from chunk text. (+23 more)

### Community 23 - "Community 23"
Cohesion: 0.05
Nodes (21): build_backend_health_payload(), _overall_status(), _probe_downstream_services(), _probe_service(), Shared health payload helpers for backend routes., Probe a downstream service health endpoint., Probe all known downstream services in parallel., _temp_storage_payload() (+13 more)

### Community 24 - "Community 24"
Cohesion: 0.07
Nodes (48): _assemble_code_chunks(), _build_knowledge_records(), _build_placeholder_records(), _calculate_overlap(), _chunk_by_headings(), _chunk_code_file(), _chunk_paragraphs(), _chunk_settings() (+40 more)

### Community 25 - "Community 25"
Cohesion: 0.08
Nodes (38): get_metrics_snapshot(), get_metrics_store(), increment_counter(), log_event(), _metric_key(), Structured logging and lightweight in-process metrics., Record a routing attempt with metrics and structured log., Record that the entire TTS fallback chain was exhausted. (+30 more)

### Community 26 - "Community 26"
Cohesion: 0.06
Nodes (22): BatchNorm2d, ExponentialMovingAverage, GroupNorm, InstanceNorm1d, InstanceNorm2d, LayerNorm, PCEN, Library implementing normalization.  Authors  * Mirco Ravanelli 2020  * Guillerm (+14 more)

### Community 27 - "Community 27"
Cohesion: 0.09
Nodes (37): _append_summary_block(), _archive_old_transcripts(), _build_daily_summaries(), _build_summary_records(), _collect_unique(), _cosine_similarity(), _daily_file_has_fingerprint(), DailyMemorySummary (+29 more)

### Community 28 - "Community 28"
Cohesion: 0.08
Nodes (20): TASK-21: Tests for daily memory writeback and re-index hooks., Summary block is appended to memory/YYYY-MM-DD.md., Same summary text written twice should be deduplicated., Existing transcript content should not be destroyed., Writeback should trigger run_memory_maintenance., Writeback should log memory_writeback_completed event., Summary block format should contain required fields., Records with identical vectors should be merged (newer wins). (+12 more)

### Community 29 - "Community 29"
Cohesion: 0.09
Nodes (19): _make_api_status_error(), _make_rate_limit_error(), TASK-22: Tests for key pool manager and quota-aware routing., mark_success resets consecutive failures and cooldown., When all keys are in cooldown, select_key returns the earliest-expiring one., all_states returns a snapshot of all key states., Stub config.get_settings for provider router tests., Stub external deps so key_pool and provider_router can be imported. (+11 more)

### Community 30 - "Community 30"
Cohesion: 0.1
Nodes (18): _make_record(), TASK-20: Tests for retrieval and reranking service., retrieve_context returns both knowledge and memory results., Results respect configured top-k limits., Results should be ordered by distance (ascending)., Memory results get a distance bonus in reranking., Diagnostics should contain candidate counts and top hits., retrieve_context should log a retrieval_completed event. (+10 more)

### Community 31 - "Community 31"
Cohesion: 0.09
Nodes (19): ImportanceResult, _match_patterns(), Heuristic importance scoring for memory records., Immutable result of importance scoring., Score the importance of a piece of text using regex heuristics.      Returns an, Return signal labels for all patterns that match *text*., score_importance(), Tests for memory importance scoring heuristics. (+11 more)

### Community 32 - "Community 32"
Cohesion: 0.11
Nodes (23): _empty_bundle_with_project(), FakeRetrievalBundle, load_tool_modules(), make_fake_agent_loop(), _make_fake_embedder(), _make_fake_retrieval(), Shared test fixtures for brain API tests., Register fake modules for all heavy dependencies of ``core.chat_service``. (+15 more)

### Community 33 - "Community 33"
Cohesion: 0.09
Nodes (28): _build_document_summary(), create_workspace_directory(), delete_workspace_directory(), delete_workspace_document(), list_knowledge_base_directories(), list_knowledge_base_documents(), list_workspace_documents(), move_workspace_document() (+20 more)

### Community 34 - "Community 34"
Cohesion: 0.1
Nodes (17): TASK-24: Tests for routing observability and circuit-breaker metrics., Failed route should increment llm_provider_failures_total., record_fallback_hop should increment llm_fallback_hops_total., record_chain_exhausted should increment llm_chain_exhausted_total., record_route_attempt should observe llm_route_latency_ms., Circuit should open after _CIRCUIT_OPEN_THRESHOLD consecutive failures., Circuit should close after a successful request., Circuit state changes should be recorded in metrics. (+9 more)

### Community 35 - "Community 35"
Cohesion: 0.16
Nodes (27): _array_object_item_schema(), _build_event_definition(), _build_python_field_args(), _class_names(), _collect_nested_types(), _definitions_for_direction(), _event_name_from_class_name(), _event_names() (+19 more)

### Community 36 - "Community 36"
Cohesion: 0.11
Nodes (14): _convert_with_docling(), _convert_with_markitdown(), DoclingServiceError, DocumentIngestionError, _get_docling_converter(), _get_md_converter(), ingest_document(), Document ingestion via Docling with MarkItDown fallback. (+6 more)

### Community 37 - "Community 37"
Cohesion: 0.13
Nodes (6): DiscreteVAE, DiscretizationLoss, get_codebook_indices(), Quantize, ResBlock, UpsampledConv

### Community 38 - "Community 38"
Cohesion: 0.17
Nodes (24): _client_init_payload(), _generated_protocol_contracts(), _import(), _protocol_events(), _server_init_ack_payload(), test_check_version_compatible_uses_major_version(), test_generated_python_contracts_module_is_available(), test_load_protocol_contract_exposes_versioned_machine_readable_schemas() (+16 more)

### Community 39 - "Community 39"
Cohesion: 0.08
Nodes (5): Tests for the dreaming scoring engine., TestBuildSignals, TestNormalisers, TestPassesThreshold, TestScoreCandidate

### Community 40 - "Community 40"
Cohesion: 0.1
Nodes (13): convert_audio_with_ffmpeg(), _load_model(), make_wav_header(), _patch_tokenizer_config(), VibeVoice TTS serve — uses transformers native VibeVoice 1.5B., Run TTS inference (blocking) and return WAV bytes., Fix extra_special_tokens from list to object if needed (community HF conversion, Load the VibeVoice 1.5B model via pengzhiliang/transformers fork. (+5 more)

### Community 41 - "Community 41"
Cohesion: 0.18
Nodes (11): TASK-23: Tests for model and provider fallback chain execution., 429 on first hop should trigger fallback to next hop., Stub external deps for fallback chain testing., Chain should stop after max hops even if all fail., All hops in a chain share the same trace_id., 5xx on first hop should trigger fallback to next hop., Each hop attempt and result should be logged., _stub_config() (+3 more)

### Community 42 - "Community 42"
Cohesion: 0.17
Nodes (19): build_signals(), _clamp(), normalise_consolidation(), normalise_frequency(), normalise_query_diversity(), normalise_recency(), normalise_relevance(), _parse_date() (+11 more)

### Community 43 - "Community 43"
Cohesion: 0.18
Nodes (18): _build_seed_record(), _create_missing_tables(), ensure_fts_index(), ensure_tables(), get_db(), get_knowledge_table(), get_memories_table(), get_table() (+10 more)

### Community 44 - "Community 44"
Cohesion: 0.18
Nodes (14): FakeRelay, _load_main(), Tests for the FastAPI entrypoint., test_app_import_avoids_on_event_deprecation(), test_convert_lazily_initializes_markitdown_once(), test_convert_rejects_oversized_upload(), test_convert_returns_upload_failed_code_when_conversion_crashes(), test_create_speech_uses_backend_tts_cache_when_hit() (+6 more)

### Community 45 - "Community 45"
Cohesion: 0.18
Nodes (10): _import_light(), Tests for the Light Phase — candidate collection and dedup., Stub config, workspace, embedder, and recall_tracker., Write a fake daily file with a summary block., _stub_deps(), TestBuildTraceStats, TestCollectDailyFragments, TestExtractSummaryBlocks (+2 more)

### Community 46 - "Community 46"
Cohesion: 0.26
Nodes (17): _fake_request(), _module(), Tests for protocol.message_envelope — normalize, enrich, BrainMessage., Build a minimal FastAPI Request mock., test_brain_message_metadata_is_defensive_copy(), test_build_envelope_auto_generates_trace_id(), test_build_envelope_enriches_trace_id_from_header(), test_build_envelope_from_flat_body() (+9 more)

### Community 47 - "Community 47"
Cohesion: 0.12
Nodes (8): _clean_plugins(), Tests for worker functions., Reset plugin singletons between tests., TestPluginSingletons, TestProcessApiTool, TestProcessCamera, TestProcessMedia, TestProcessWebCrawler

### Community 48 - "Community 48"
Cohesion: 0.29
Nodes (14): _configure_workspace(), _import(), _stub_db_module(), test_archive_session_turn_writes_into_persona_subdirectory(), test_clone_persona_scaffold_copies_core_docs_from_source(), test_create_persona_scaffold_creates_core_files_and_rejects_duplicates(), test_delete_persona_scaffold_removes_custom_persona_only(), test_is_indexable_document_skips_persona_core_docs() (+6 more)

### Community 49 - "Community 49"
Cohesion: 0.16
Nodes (15): _build_project_info(), create_project(), delete_project(), get_project_info(), list_projects(), _next_available_project_id(), Project CRUD: list, create, delete, and inspect projects., Read the project label file, falling back to the directory name. (+7 more)

### Community 50 - "Community 50"
Cohesion: 0.27
Nodes (9): FakeTransport, _load_module(), Tests for the Brain-owned Gemini Live session manager., test_gemini_live_session_drops_audio_during_reconnect(), test_gemini_live_session_keepalive_pings_transport(), test_gemini_live_session_marks_transport_unavailable_after_max_retries(), test_gemini_live_session_reconnects_after_listener_failure(), test_gemini_live_session_reuses_transport_across_text_turns() (+1 more)

### Community 51 - "Community 51"
Cohesion: 0.19
Nodes (9): _import_tracker(), _make_fake_config(), Tests for recall_tracker — JSONL write/read/rotate., Return a fake settings object with workspace pointing to tmp_path., Replace config and workspace helpers with test stubs., _stub_deps(), TestReadTraces, TestRecordTrace (+1 more)

### Community 52 - "Community 52"
Cohesion: 0.21
Nodes (14): _fake_image(), _make_mock_openai_client(), Tests for image ingestion., Create a minimal valid PNG file., test_all_fail_returns_fallback_message(), test_empty_ocr_falls_through(), test_ocr_when_no_api_key(), test_ocr_when_vision_fails() (+6 more)

### Community 53 - "Community 53"
Cohesion: 0.18
Nodes (9): Tests for ERRORS.md rotation and archival., Duplicate detection should still work on the trimmed file., Stub workspace and config for learnings module., No archival when line count is under max_lines., Rotation should archive old lines when exceeding max_lines., Archived file should contain the overflow lines., Lines from different months should go to different archive files., _stub_deps() (+1 more)

### Community 54 - "Community 54"
Cohesion: 0.2
Nodes (9): _import_rem(), Tests for the REM Phase — embedding clustering and theme extraction., Stub config, workspace, embedder, and recall_tracker., Write fake recall traces JSONL file., _stub_deps(), TestExtractUniqueQueries, TestKmeans, TestRunRemPhase (+1 more)

### Community 55 - "Community 55"
Cohesion: 0.35
Nodes (13): delete_document_meta(), get_doc_meta_path(), get_document_meta(), list_disabled_document_paths(), load_doc_meta(), move_document_meta(), _normalize_entry(), _now_iso() (+5 more)

### Community 56 - "Community 56"
Cohesion: 0.23
Nodes (13): get_search_table(), _hybrid_search(), _matches_disabled_knowledge_path(), _matches_persona(), 語意檢索與結果整理 — 支援 vector-only 與 hybrid (vector + FTS) 搜索。, Try hybrid search (vector + FTS), fall back to vector-only., 根據請求表名回傳對應資料表，維持既有預設行為。, Execute search and return persona-filtered results.      When *query_text* is pr (+5 more)

### Community 57 - "Community 57"
Cohesion: 0.24
Nodes (6): _load_chat_service(), _make_generation_context(), _stub_finalize_dependencies(), test_stream_generation_error_yields_no_done_event(), test_stream_generation_skip_tools_uses_native_stream(), test_stream_generation_with_tools_uses_native_stream_after_tool_phase()

### Community 58 - "Community 58"
Cohesion: 0.17
Nodes (8): Implementation of a sine-based periodic activation function     Shape:         -, Forward pass of the function.         Applies the function to the input elementw, Initialization.         INPUT:             - in_features: shape of the input, Forward pass of the function.         Applies the function to the input elementw, A modified Snake function which uses separate parameters for the magnitude of th, Initialization.         INPUT:             - in_features: shape of the input, Snake, SnakeBeta

### Community 59 - "Community 59"
Cohesion: 0.15
Nodes (2): Tests for the Redis-backed TTS cache helpers., TestMakeCacheKey

### Community 60 - "Community 60"
Cohesion: 0.23
Nodes (11): _mock_paths(), Tests for parse_identity() in knowledge.workspace., Create a minimal workspace with IDENTITY.md., Return a dict matching resolve_core_document_paths output., When persona has its own IDENTITY.md, parse_identity returns overridden values., test_parse_identity_extracts_fields_from_markdown(), test_parse_identity_ignores_unknown_keys(), test_parse_identity_partial_fields_use_defaults() (+3 more)

### Community 61 - "Community 61"
Cohesion: 0.21
Nodes (5): _mock_health_client(), Tests for backend health routes., Return a patch context that injects a mock httpx client into app.main._health_cl, TestHealthzDegraded, TestHealthzOk

### Community 62 - "Community 62"
Cohesion: 0.24
Nodes (10): _local_cfg(), _openai_cfg(), Tests for audio ingestion., test_local_nonzero_exit(), test_local_success_from_file(), test_local_success_from_stdout(), test_openai_failure_returns_fallback(), test_openai_success() (+2 more)

### Community 63 - "Community 63"
Cohesion: 0.3
Nodes (11): _migrate_index_state(), _migrate_lancedb(), _migrate_learnings(), _migrate_sessions_db(), _migrate_workspace(), _move_if_needed(), Migrate legacy flat data layout to per-project directory structure.  Legacy layo, Move a file or directory from src to dst if src exists and dst does not. (+3 more)

### Community 64 - "Community 64"
Cohesion: 0.27
Nodes (10): cache_get(), cache_put(), _decode_cache_payload(), make_cache_key(), TTS Redis cache layer — async, gracefully degrades if Redis is unavailable., Store an entry in Redis. Errors are recorded and otherwise ignored., Return the Redis key for a TTS payload., Fetch an entry from Redis. Returns None on miss or error. (+2 more)

### Community 65 - "Community 65"
Cohesion: 0.31
Nodes (10): build_health_payload(), get_db(), get_metrics_store(), get_settings(), list_personas(), list_sessions_for_project(), list_workspace_documents(), _probe() (+2 more)

### Community 66 - "Community 66"
Cohesion: 0.31
Nodes (6): _import_deep(), Tests for the Deep Phase — scoring, dedup, and promotion., Stub config, workspace, embedder, and infra.db., _stub_deps(), TestRunDeepPhase, _write_candidates()

### Community 67 - "Community 67"
Cohesion: 0.2
Nodes (0): 

### Community 68 - "Community 68"
Cohesion: 0.36
Nodes (7): _make_response(), _mock_cfg(), Tests for backend brain proxy facade routes., test_explicit_brain_routes_still_forward_options(), test_gateway_brain_proxy_closes_sse_upstream(), test_gateway_brain_proxy_forwards_to_brain_api(), test_gateway_brain_proxy_returns_502_when_upstream_disconnects()

### Community 69 - "Community 69"
Cohesion: 0.24
Nodes (3): _client(), FakeLiveSession, test_internal_live_bridge_routes_text_audio_and_close()

### Community 70 - "Community 70"
Cohesion: 0.62
Nodes (9): _configure_workspace(), _import(), _stub_knowledge_admin_deps(), test_document_summary_reads_existing_meta(), test_manual_note_writes_manual_meta(), test_move_and_delete_document_sync_meta(), test_uploaded_artifact_is_saved_under_raw_without_doc_meta(), test_uploaded_document_writes_default_meta() (+1 more)

### Community 71 - "Community 71"
Cohesion: 0.39
Nodes (8): brain_proxy(), documented_brain_proxy(), _filter_headers(), _proxy_to_brain(), Reverse proxy: forward backend facade routes to the Brain service., _request_brain_path(), _stream_upstream_bytes(), _target_url()

### Community 72 - "Community 72"
Cohesion: 0.39
Nodes (8): _load_embedder(), Tests for provider-aware embedding adapters., test_bge_embedder_builds_local_model(), test_encode_query_with_fallback_skips_versions_without_tables(), test_encode_query_with_fallback_uses_next_version_after_error(), test_gemini_embedder_uses_batch_embed_request(), test_openai_embedder_uses_embeddings_client(), test_voyage_embedder_uses_query_input_type()

### Community 73 - "Community 73"
Cohesion: 0.28
Nodes (4): generateOutputFrame(), hasEnoughDataForFrame(), o, stream()

### Community 74 - "Community 74"
Cohesion: 0.39
Nodes (7): get_job_status(), _job_key(), Job status storage for async gateway tasks., Fetch the latest job status from Redis, falling back to memory., Persist the latest job status in Redis, with in-memory fallback., _read_from_redis(), set_job_status()

### Community 75 - "Community 75"
Cohesion: 0.36
Nodes (1): TTSStressTester

### Community 76 - "Community 76"
Cohesion: 0.43
Nodes (7): _mock_cfg(), _ok_response(), Tests for forward module., test_default_empty_media_refs(), test_forward_error_does_not_raise(), test_successful_forward(), TestForwardToBrain

### Community 77 - "Community 77"
Cohesion: 0.29
Nodes (7): ensure_utc(), normalize_iso_timestamp(), Shared UTC datetime utilities for consistent timestamp handling., Ensure a datetime is UTC-aware, assuming UTC if naive., Parse an ISO timestamp and normalize to UTC-aware ISO string.      Returns empty, Return current UTC time as ISO-formatted string with timezone., utc_now_iso()

### Community 78 - "Community 78"
Cohesion: 0.33
Nodes (2): I18nAuto, load_language_list()

### Community 79 - "Community 79"
Cohesion: 0.48
Nodes (6): Regression tests for the single-container backend stack., _read_text(), test_backend_compose_uses_env_file_instead_of_inline_defaults(), test_backend_env_example_prefers_local_index_tts_and_redis(), test_backend_image_starts_local_redis_and_index_tts(), test_root_compose_uses_single_backend_container()

### Community 80 - "Community 80"
Cohesion: 0.33
Nodes (0): 

### Community 81 - "Community 81"
Cohesion: 0.33
Nodes (1): Tests for TTS router configuration loading.

### Community 82 - "Community 82"
Cohesion: 0.33
Nodes (2): Tests for DLQ (dead-letter queue) functionality., TestPushToDlq

### Community 83 - "Community 83"
Cohesion: 0.33
Nodes (1): TestTTSPipeline

### Community 84 - "Community 84"
Cohesion: 0.4
Nodes (5): Slash command resolver — rewrites /command messages into LLM-friendly instructio, A rewritten user message that instructs the LLM to call a specific tool., If message starts with /skill_id, rewrite it to instruct the LLM to call the too, SlashRewrite, try_rewrite_slash()

### Community 85 - "Community 85"
Cohesion: 0.47
Nodes (3): _load_db(), Tests for active embedding version table routing., TestVectorTableNaming

### Community 86 - "Community 86"
Cohesion: 0.33
Nodes (1): DinetRenderer

### Community 87 - "Community 87"
Cohesion: 0.6
Nodes (4): build_error_response(), build_http_error(), Shared HTTP error payload helpers for backend routes., upload_failed_response()

### Community 88 - "Community 88"
Cohesion: 0.5
Nodes (3): get_redis(), Redis connection singleton for the gateway., redis_available()

### Community 89 - "Community 89"
Cohesion: 0.7
Nodes (4): chinese_path_compile_support(), _create_build_dir(), _get_cuda_bare_metal_version(), load()

### Community 90 - "Community 90"
Cohesion: 0.5
Nodes (3): extract_i18n_strings(), scan the directory for all .py files (recursively)     for each file, parse the, scan_i18n_strings()

### Community 91 - "Community 91"
Cohesion: 0.7
Nodes (4): _client(), test_internal_enrich_accepts_forward_payload_and_stores_system_message(), test_internal_enrich_accepts_gateway_spec_payload_shape(), test_internal_enrich_rejects_empty_context_payload()

### Community 92 - "Community 92"
Cohesion: 0.5
Nodes (3): clean_for_tts(), Strip markdown and other non-speech artifacts from text before TTS synthesis., Remove markdown formatting, keeping readable spoken text.

### Community 93 - "Community 93"
Cohesion: 0.5
Nodes (0): 

### Community 94 - "Community 94"
Cohesion: 0.5
Nodes (1): TestMarkItDown

### Community 95 - "Community 95"
Cohesion: 0.5
Nodes (1): Tests for backend dependency expectations.

### Community 96 - "Community 96"
Cohesion: 0.83
Nodes (3): _make_config(), _ok_result(), test_targeted_provider_fallback_resets_voice_for_edge()

### Community 97 - "Community 97"
Cohesion: 0.5
Nodes (3): dreams_dir(), Shared path helpers and constants for the dreaming subsystem., Return the .dreams state directory for a project.

### Community 98 - "Community 98"
Cohesion: 0.83
Nodes (3): _load_main_module(), _stub_module(), test_save_knowledge_document_route_schedules_background_reindex()

### Community 99 - "Community 99"
Cohesion: 0.67
Nodes (0): 

### Community 100 - "Community 100"
Cohesion: 0.67
Nodes (1): CLI entrypoint: rebuild the knowledge vector index from workspace documents.  Us

### Community 101 - "Community 101"
Cohesion: 0.67
Nodes (0): 

### Community 102 - "Community 102"
Cohesion: 1.0
Nodes (2): main(), _resolve_graphify_python()

### Community 103 - "Community 103"
Cohesion: 1.0
Nodes (2): main(), _resolve_graphify_python()

### Community 104 - "Community 104"
Cohesion: 1.0
Nodes (0): 

### Community 105 - "Community 105"
Cohesion: 1.0
Nodes (0): 

### Community 106 - "Community 106"
Cohesion: 1.0
Nodes (0): 

### Community 107 - "Community 107"
Cohesion: 1.0
Nodes (0): 

### Community 108 - "Community 108"
Cohesion: 1.0
Nodes (0): 

### Community 109 - "Community 109"
Cohesion: 1.0
Nodes (1): 将tokenize后的结果按特定token进一步分割

### Community 110 - "Community 110"
Cohesion: 1.0
Nodes (1): When Redis is unavailable, DLQ push is skipped without raising.

### Community 111 - "Community 111"
Cohesion: 1.0
Nodes (1): When Redis lpush fails, error is logged but not raised.

### Community 112 - "Community 112"
Cohesion: 1.0
Nodes (1): Fire-and-forget: errors are logged but not raised.

### Community 113 - "Community 113"
Cohesion: 1.0
Nodes (1): Combine the legacy single key and the new key-pool env into one list.         If

### Community 114 - "Community 114"
Cohesion: 1.0
Nodes (1): Return the primary and fallback models without duplicates.

### Community 115 - "Community 115"
Cohesion: 1.0
Nodes (1): Parse LLM_FALLBACK_CHAIN into (provider, model) pairs.          Format: ``provid

### Community 116 - "Community 116"
Cohesion: 1.0
Nodes (1): Provide a sane default base URL per provider.

### Community 117 - "Community 117"
Cohesion: 1.0
Nodes (1): Return a snapshot of all key states (for diagnostics).

### Community 118 - "Community 118"
Cohesion: 1.0
Nodes (1): Create a successful tool result.

### Community 119 - "Community 119"
Cohesion: 1.0
Nodes (1): Create a failed tool result.

### Community 120 - "Community 120"
Cohesion: 1.0
Nodes (0): 

### Community 121 - "Community 121"
Cohesion: 1.0
Nodes (0): 

### Community 122 - "Community 122"
Cohesion: 1.0
Nodes (0): 

### Community 123 - "Community 123"
Cohesion: 1.0
Nodes (0): 

### Community 124 - "Community 124"
Cohesion: 1.0
Nodes (0): 

### Community 125 - "Community 125"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **543 isolated node(s):** `大腦層集中設定 — 從 .env 讀取所有環境變數`, `Immutable backend settings loaded from environment.`, `Build config from environment variables (cached).`, `Shared HTTP error payload helpers for backend routes.`, `YouTube transcript ingestion via youtube-transcript-api.` (+538 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 104`** (2 nodes): `anti_alias_activation.cpp`, `PYBIND11_MODULE()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 105`** (2 nodes): `compat.h`, `type_shim.h`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 106`** (2 nodes): `cli.py`, `main()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 107`** (2 nodes): `checkpoint.py`, `load_checkpoint()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 108`** (1 nodes): `convert_hf_format.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 109`** (1 nodes): `将tokenize后的结果按特定token进一步分割`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 110`** (1 nodes): `When Redis is unavailable, DLQ push is skipped without raising.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 111`** (1 nodes): `When Redis lpush fails, error is logged but not raised.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 112`** (1 nodes): `Fire-and-forget: errors are logged but not raised.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 113`** (1 nodes): `Combine the legacy single key and the new key-pool env into one list.         If`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 114`** (1 nodes): `Return the primary and fallback models without duplicates.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 115`** (1 nodes): `Parse LLM_FALLBACK_CHAIN into (provider, model) pairs.          Format: ``provid`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 116`** (1 nodes): `Provide a sane default base URL per provider.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 117`** (1 nodes): `Return a snapshot of all key states (for diagnostics).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 118`** (1 nodes): `Create a successful tool result.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 119`** (1 nodes): `Create a failed tool result.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 120`** (1 nodes): `protocol-contracts.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 121`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 122`** (1 nodes): `json.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 123`** (1 nodes): `speech-recognition.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 124`** (1 nodes): `tailwind.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 125`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `UnifiedVoice` connect `Community 12` to `Community 9`, `Community 19`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Why does `TTSRouterConfig` connect `Community 0` to `Community 4`, `Community 5`, `Community 36`, `Community 15`, `Community 81`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `IndexTTS` connect `Community 19` to `Community 40`, `Community 12`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Are the 85 inferred relationships involving `TTSRouterConfig` (e.g. with `get_tts_config()` and `BrainLiveRelay`) actually correct?**
  _`TTSRouterConfig` has 85 INFERRED edges - model-reasoned connections that need verification._
- **Are the 75 inferred relationships involving `SynthesizeRequest` (e.g. with `LiveVoicePipeline` and `Live voice pipeline: orchestrates Brain token stream to TTS audio chunks.  Uses`) actually correct?**
  _`SynthesizeRequest` has 75 INFERRED edges - model-reasoned connections that need verification._
- **Are the 62 inferred relationships involving `NormalizedTTSResult` (e.g. with `SpeechRequest` and `Weather skill implementation.`) actually correct?**
  _`NormalizedTTSResult` has 62 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `SessionStore` (e.g. with `ProjectContext` and `Project-scoped context: paths, DB connections, and session stores.`) actually correct?**
  _`SessionStore` has 29 INFERRED edges - model-reasoned connections that need verification._
# Implementation Tasks: LLM Multi-Provider Failover

## 1. Core Logic & Config
- [ ] 1.1 Ensure `BrainSettings` in `config.py` correctly resolves `llm_fallback_chain` <!-- id: 101 -->
- [ ] 1.2 Finalize `RouteHop` and `build_fallback_chain` in `fallback_chain.py` <!-- id: 102 -->

## 2. LLM Client Integration
- [ ] 2.1 Refactor `llm_client.py` sync completions to use the fallback chain <!-- id: 201 -->
- [ ] 2.2 Refactor `llm_client.py` async streaming to use the fallback chain with proper `yield` logic <!-- id: 202 -->
- [ ] 2.3 Implement robust error classification and logging for each hop <!-- id: 203 -->

## 3. Testing & Verification
- [ ] 3.1 Create mock-based tests for 429 triggers (`tests/test_llm_fallback_chain.py`) <!-- id: 301 -->
- [ ] 3.2 Verify cross-provider connectivity (Gemini -> OpenAI mock) <!-- id: 302 -->
- [ ] 3.3 Verify max hops limit prevents infinite loops <!-- id: 303 -->

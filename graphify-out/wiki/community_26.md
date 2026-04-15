# Community 26

Nodes: 32

## Members
- **test_retrieval_service.py** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **_stub_deps()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **_make_record()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **TestRetrievalService** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_returns_knowledge_and_memory_results()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_top_k_matches_config()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_rerank_orders_by_distance()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_memory_distance_bonus_applies()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_diagnostics_contains_required_fields()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_diagnostics_logs_retrieval_event()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_empty_tables_return_empty_results()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_retrieval_bundle_is_frozen()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_decay_penalizes_old_records()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_decay_zero_has_no_effect()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_missing_date_no_decay_penalty()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_importance_boosts_high_importance_records()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **.test_selected_embedding_version_is_used_for_search()** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **TASK-20: Tests for retrieval and reranking service.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Stub all heavy deps and return fresh retrieval_service module.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **retrieve_context returns both knowledge and memory results.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Results respect configured top-k limits.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Results should be ordered by distance (ascending).** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Memory results get a distance bonus in reranking.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Diagnostics should contain candidate counts and top hits.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **retrieve_context should log a retrieval_completed event.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Empty knowledge/memory tables should return empty results without error.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **RetrievalBundle should be immutable.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Older memory records should rank lower due to time decay.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **With decay_rate=0, old and new records rank the same by distance.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Records without a date field should not be penalized by decay.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **Records with higher importance should rank better.** (`brain/api/tests/knowledge/test_retrieval_service.py`)
- **retrieve_context passes the selected embedding version to search.** (`brain/api/tests/knowledge/test_retrieval_service.py`)

## Connections to other communities

# Community 30

Nodes: 28

## Members
- **test_routing_observability.py** (`brain/api/tests/services/test_routing_observability.py`)
- **_stub_deps()** (`brain/api/tests/services/test_routing_observability.py`)
- **_stub_config()** (`brain/api/tests/services/test_routing_observability.py`)
- **TestRoutingMetrics** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_route_attempt_increments_counter()** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_provider_failure_increments_failure_counter()** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_fallback_hop_increments_counter()** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_chain_exhausted_increments_counter()** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_route_latency_is_observed()** (`brain/api/tests/services/test_routing_observability.py`)
- **TestCircuitBreakerMetrics** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_circuit_opens_after_threshold_failures()** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_circuit_closes_on_success()** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_circuit_state_change_is_logged()** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_auth_failure_opens_circuit_immediately()** (`brain/api/tests/services/test_routing_observability.py`)
- **TestChainExecutionMetrics** (`brain/api/tests/services/test_routing_observability.py`)
- **.test_chain_failure_produces_metrics()** (`brain/api/tests/services/test_routing_observability.py`)
- **TASK-24: Tests for routing observability and circuit-breaker metrics.** (`brain/api/tests/services/test_routing_observability.py`)
- **Stub deps and return fresh modules with a real MetricsStore.** (`brain/api/tests/services/test_routing_observability.py`)
- **record_route_attempt should increment llm_route_attempts_total.** (`brain/api/tests/services/test_routing_observability.py`)
- **Failed route should increment llm_provider_failures_total.** (`brain/api/tests/services/test_routing_observability.py`)
- **record_fallback_hop should increment llm_fallback_hops_total.** (`brain/api/tests/services/test_routing_observability.py`)
- **record_chain_exhausted should increment llm_chain_exhausted_total.** (`brain/api/tests/services/test_routing_observability.py`)
- **record_route_attempt should observe llm_route_latency_ms.** (`brain/api/tests/services/test_routing_observability.py`)
- **Circuit should open after _CIRCUIT_OPEN_THRESHOLD consecutive failures.** (`brain/api/tests/services/test_routing_observability.py`)
- **Circuit should close after a successful request.** (`brain/api/tests/services/test_routing_observability.py`)
- **Circuit state changes should be recorded in metrics.** (`brain/api/tests/services/test_routing_observability.py`)
- **Auth invalid should immediately open circuit.** (`brain/api/tests/services/test_routing_observability.py`)
- **A failed chain execution should produce route attempt + chain exhausted metrics.** (`brain/api/tests/services/test_routing_observability.py`)

## Connections to other communities

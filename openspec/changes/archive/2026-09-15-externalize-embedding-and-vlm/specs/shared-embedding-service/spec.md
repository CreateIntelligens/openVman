## ADDED Requirements

### Requirement: Standalone multi-provider embedding gateway
The system SHALL provide a standalone embedding gateway that owns local BGE inference and configured remote-provider adapters without loading model weights or embedding-provider clients in Brain.

#### Scenario: Batch encoding succeeds
- **WHEN** a client submits one or more texts to the embedding gateway
- **THEN** the gateway returns one dense vector per input in the original order

#### Scenario: Brain handles all embedding requests remotely
- **WHEN** Brain needs a query, document, or memory embedding
- **THEN** Brain sends the request to `EMBEDDING_SERVICE_URL` and does not construct an in-process BGE, Gemini, OpenAI, or Voyage adapter

### Requirement: Gateway-owned provider fallback
The embedding gateway SHALL execute the configured provider fallback order, apply bounded retry and cooldown policy, and use exactly one embedding identity for every vector in a single response.

#### Scenario: Preferred provider fails
- **WHEN** the first acceptable provider fails and a later acceptable provider is healthy
- **THEN** the gateway encodes the complete batch with the later provider and reports the selected identity plus sanitized attempt outcomes

#### Scenario: Provider fails after partial batch work
- **WHEN** a provider cannot complete the full batch
- **THEN** the gateway discards that provider's partial result and does not mix it with vectors from another provider

#### Scenario: Gateway is unreachable
- **WHEN** the embedding gateway process cannot be reached
- **THEN** Brain reports the gateway unavailable and does not recreate provider fallback locally

### Requirement: Caller constrains acceptable embedding identities
The gateway SHALL attempt only the ordered embedding identities supplied or authorized by the request, and Brain SHALL derive query candidates from identities with queryable vector tables.

#### Scenario: Query has two compatible indexes
- **WHEN** Brain has queryable tables for two configured identities
- **THEN** Brain submits those identities in preferred order and the gateway may select either one through fallback

#### Scenario: Fallback table is missing
- **WHEN** Brain has no queryable table for a fallback identity
- **THEN** Brain omits that identity and the gateway does not return vectors from it for that query

#### Scenario: Write fallback is not authorized
- **WHEN** an indexing or memory-write request specifies one write identity without fallback permission
- **THEN** the gateway either returns that identity or fails without selecting another model

### Requirement: Every response reports the effective embedding specification
Every successful non-empty or empty embedding response SHALL report a stable identity, provider, exact model, dense-vector dimensions, output data type, normalization behavior, input semantics, and model or service revision without exposing credentials or secret-bearing URLs.

#### Scenario: Local BGE response identifies its contract
- **WHEN** BGE-M3 successfully serves a query embedding
- **THEN** the response identifies the exact BGE model/revision, dimensions, float data type, normalization method, query semantics, and stable identity

#### Scenario: Fallback changes the effective model
- **WHEN** the gateway selects a fallback provider
- **THEN** the response metadata and top-level model identify the fallback result rather than the failed preferred model

#### Scenario: Empty batch is accepted
- **WHEN** a client submits an empty input batch
- **THEN** the gateway returns no vectors but still resolves and reports the selected embedding specification without invoking inference

### Requirement: JTAI-compatible embedding endpoint
The gateway SHALL accept `POST /embed` requests containing `texts` and `input_type`, retain the `vectors` response field expected by the current JTAI client, and add effective model metadata without changing vector ordering.

#### Scenario: Query request uses compatibility contract
- **WHEN** a client posts `{"texts":["query"],"input_type":"query"}` to `/embed`
- **THEN** the response contains exactly one vector under `vectors` plus `model`, `embedding_spec`, and fallback attempt metadata

#### Scenario: Existing JTAI client ignores extensions
- **WHEN** a client reads only the response's `vectors` field
- **THEN** the added metadata does not prevent it from consuming the vectors

### Requirement: OpenAI-compatible embedding endpoint
The gateway SHALL expose `POST /v1/embeddings` with OpenAI-compatible request and response fields and additive extension metadata for the effective embedding specification and fallback attempts.

#### Scenario: OpenAI client embeds a batch
- **WHEN** an OpenAI-compatible client submits multiple input strings and a model or gateway alias
- **THEN** the gateway returns indexed embedding data entries in input order, the effective top-level `model`, and standard usage fields

#### Scenario: Retrieval semantics are requested
- **WHEN** a client supplies the supported query or document input-type extension
- **THEN** the gateway maps it to the selected provider's retrieval semantics and reports the resolved semantics in the response specification

### Requirement: Model discovery and provider-ready health
The gateway SHALL expose discoverable model specifications separately from process liveness and SHALL report preferred-route and fallback-provider readiness without exposing credentials.

#### Scenario: Client lists embedding models
- **WHEN** a client calls `GET /v1/models`
- **THEN** the gateway returns configured public model identities and vector-relevant specifications with no secrets

#### Scenario: Liveness before model load
- **WHEN** the process is running but no configured embedding provider is ready
- **THEN** `/health` reports the process alive while `/health/ready` reports unavailable

#### Scenario: Preferred provider is unavailable
- **WHEN** the preferred provider fails readiness but an authorized fallback is usable
- **THEN** `/health/ready` reports degraded readiness and identifies the usable fallback specification

### Requirement: Client rejects an incompatible or unexpected response
Brain SHALL fail an operation when the returned identity was not requested, the reported dimension does not match the vector, or the identity does not map to the intended isolated index.

#### Scenario: Gateway returns an unrequested identity
- **WHEN** Brain receives a successful response whose identity was not among the acceptable candidates
- **THEN** Brain rejects the response and does not query or write a vector table

#### Scenario: Reported dimension is inconsistent
- **WHEN** a response vector length differs from `embedding_spec.dimensions`
- **THEN** Brain rejects the complete batch and reports an incompatible gateway response

### Requirement: Bounded remote execution
The gateway and its clients SHALL use bounded request sizes, timeouts, batch sizes, provider attempts, and inference concurrency so one backfill cannot starve interactive queries indefinitely.

#### Scenario: Large backfill is chunked
- **WHEN** Brain submits more texts than the configured remote chunk size
- **THEN** the client divides them into bounded requests and reassembles same-identity vectors in input order

#### Scenario: All provider attempts fail
- **WHEN** every acceptable provider times out or fails
- **THEN** the gateway returns a sanitized aggregate failure and no partial vectors

### Requirement: Optional service authentication
The embedding gateway SHALL support bearer-token authentication and SHALL require it whenever the service is routed through nginx outside its private Docker network.

#### Scenario: Protected route rejects missing token
- **WHEN** token enforcement is enabled and a request omits or supplies an invalid bearer token
- **THEN** the gateway rejects the request without running provider inference

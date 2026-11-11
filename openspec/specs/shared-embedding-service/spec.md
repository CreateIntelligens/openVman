# shared-embedding-service Specification

## Purpose
TBD - created by archiving change externalize-embedding-and-vlm. Update Purpose after archive.

## Requirements

### Requirement: Standalone embedding gateway
The system SHALL provide a standalone embedding gateway that owns local EmbeddingGemma 2 inference (`EMBEDDING_GEMMA_MODEL`, default `google/embeddinggemma-2`) without loading model weights in Brain. EmbeddingGemma 2 SHALL be the only served provider; the gateway SHALL NOT include BGE or cloud embedding adapters (Gemini, OpenAI, Voyage).

#### Scenario: Batch encoding succeeds
- **WHEN** a client submits one or more texts to the embedding gateway
- **THEN** the gateway returns one dense vector per input in the original order

#### Scenario: Brain handles all embedding requests remotely
- **WHEN** Brain needs a query, document, or memory embedding
- **THEN** Brain sends the request to `EMBEDDING_SERVICE_URL` and does not construct an in-process embedding model or provider adapter

### Requirement: No provider fallback
The embedding gateway SHALL apply a failure cooldown (with periodic probes) to its provider and use exactly one embedding identity for every vector in a single response. When the provider cannot complete a request, the gateway SHALL fail it rather than switch to another model.

#### Scenario: Provider fails after partial batch work
- **WHEN** the provider cannot complete the full batch
- **THEN** the gateway discards the partial result and returns a sanitized failure with no vectors

#### Scenario: Gateway is unreachable
- **WHEN** the embedding gateway process cannot be reached
- **THEN** Brain reports the gateway unavailable and does not embed locally

### Requirement: Caller constrains the embedding identity
The gateway SHALL serve only an identity it is configured for. A request that names an identity (`identity` on `/embed`, `model` on `/v1/embeddings`) the gateway does not serve SHALL be rejected without vectors; a request that names none SHALL use EmbeddingGemma 2. Brain SHALL keep its embedding-version mechanism so a future model change can reindex into an isolated table.

#### Scenario: Unserved identity is requested
- **WHEN** a client requests an identity or model that the gateway does not serve
- **THEN** the gateway returns an error and no vectors (`/v1/embeddings` answers HTTP 400; `/embed` answers HTTP 400 for an empty batch and HTTP 503 otherwise)

### Requirement: Every response reports the effective embedding specification
Every successful non-empty or empty embedding response SHALL report a stable identity, provider, exact model, dense-vector dimensions, output data type, normalization behavior, input semantics, and model or service revision without exposing credentials or secret-bearing URLs.

#### Scenario: Response identifies its contract
- **WHEN** EmbeddingGemma 2 successfully serves a query embedding
- **THEN** the response identifies the exact model/revision, dimensions, float data type, normalization method, query semantics, and stable identity

#### Scenario: Empty batch is accepted
- **WHEN** a client submits an empty input batch
- **THEN** the gateway returns no vectors but still resolves and reports the embedding specification without invoking inference

### Requirement: JTAI-compatible embedding endpoint
The gateway SHALL accept `POST /embed` requests containing `texts` and `input_type`, retain the `vectors` response field expected by the current JTAI client, and add effective model metadata without changing vector ordering.

#### Scenario: Query request uses compatibility contract
- **WHEN** a client posts `{"texts":["query"],"input_type":"query"}` to `/embed`
- **THEN** the response contains exactly one vector under `vectors` plus `model`, `embedding_spec`, and `attempts` metadata

#### Scenario: Existing JTAI client ignores extensions
- **WHEN** a client reads only the response's `vectors` field
- **THEN** the added metadata does not prevent it from consuming the vectors

### Requirement: OpenAI-compatible embedding endpoint
The gateway SHALL expose `POST /v1/embeddings` with OpenAI-compatible request and response fields and additive extension metadata for the effective embedding specification and provider attempts.

#### Scenario: OpenAI client embeds a batch
- **WHEN** an OpenAI-compatible client submits multiple input strings and a model or gateway alias
- **THEN** the gateway returns indexed embedding data entries in input order, the effective top-level `model`, and standard usage fields

#### Scenario: Retrieval semantics are requested
- **WHEN** a client supplies the supported query or document input-type extension
- **THEN** the gateway maps it to the model's retrieval semantics and reports the resolved semantics in the response specification

### Requirement: Model discovery and provider-ready health
The gateway SHALL expose discoverable model specifications separately from process liveness and SHALL report provider readiness without exposing credentials.

#### Scenario: Client lists embedding models
- **WHEN** a client calls `GET /v1/models`
- **THEN** the gateway returns configured public model identities and vector-relevant specifications with no secrets

#### Scenario: Liveness before model load
- **WHEN** the process is running but the model is not ready
- **THEN** `/health` reports the process alive while `/health/ready` returns HTTP 503 with status `unavailable`

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
- **WHEN** the provider times out or fails
- **THEN** the gateway returns a sanitized aggregate failure and no partial vectors

### Requirement: Optional service authentication
The embedding gateway SHALL support bearer-token authentication and SHALL require it whenever the service is routed through nginx outside its private Docker network.

#### Scenario: Protected route rejects missing token
- **WHEN** token enforcement is enabled and a request omits or supplies an invalid bearer token
- **THEN** the gateway rejects the request without running provider inference

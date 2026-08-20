## ADDED Requirements

### Requirement: Explicit service URL takes precedence
The system SHALL use an explicitly configured embedding, VLM, or IndexTTS service URL as the consumer route without requiring the corresponding local GPU profile.

#### Scenario: External embedding URL is configured
- **WHEN** `EMBEDDING_SERVICE_URL` contains an external reachable URL
- **THEN** Brain uses that URL and the worktree does not require the local `embedding` profile

#### Scenario: External VLM URL is configured
- **WHEN** `VISION_LLM_BASE_URL` contains an external OpenAI-compatible URL
- **THEN** Backend uses that URL and the worktree does not require the local `vlm` profile

#### Scenario: External IndexTTS URL is configured
- **WHEN** `TTS_INDEXTTS_URL` contains an external reachable URL
- **THEN** Backend uses that URL and the worktree does not require the local `indextts` profile

### Requirement: Local services use explicit Compose profiles
The Compose configuration SHALL provide `embedding`, `vlm`, and `indextts` profiles and SHALL use internal service URLs only for required or explicitly selected local services.

#### Scenario: Fully local GPU mode
- **WHEN** `COMPOSE_PROFILES` includes `embedding,vlm,indextts` and no external service URL is set
- **THEN** Compose starts all three local services and consumers resolve them through Docker service DNS

#### Scenario: Mixed local and external mode
- **WHEN** an external embedding URL is set, `COMPOSE_PROFILES` includes `vlm`, and IndexTTS is not configured
- **THEN** Brain uses external embedding, Backend uses local VLM, and IndexTTS remains disabled

#### Scenario: IndexTTS is omitted by default
- **WHEN** `TTS_INDEXTTS_URL` is empty and `COMPOSE_PROFILES` does not include `indextts`
- **THEN** the IndexTTS container does not start and Backend does not attempt the internal IndexTTS URL

### Requirement: Direct Compose startup uses explicit routing configuration
The project SHALL use standard `docker compose` startup without a custom launcher. `.env` SHALL explicitly select required local profiles or configure external service URLs, and Compose interpolation SHALL provide matching consumer routes and credentials.

#### Scenario: Direct Compose starts required local embedding
- **WHEN** `EMBEDDING_SERVICE_URL` is unset and `COMPOSE_PROFILES` includes `embedding`
- **THEN** `docker compose up -d` starts the gateway and Brain uses `http://embedding:8009`

#### Scenario: Direct Compose sees an external URL
- **WHEN** any service URL is explicitly configured
- **THEN** the consumer preserves that URL and does not require that service's local profile

#### Scenario: Direct Compose sees no optional-service opt-in
- **WHEN** neither URL nor profile selects VLM or IndexTTS
- **THEN** Compose leaves that optional service disabled

#### Scenario: Explicit local profile and external URL coexist
- **WHEN** a service has both an explicit external URL and an explicitly listed local profile
- **THEN** the consumer uses the external URL while Compose preserves the explicitly requested local service

### Requirement: GPU consumers expose routing health
Brain and Backend health payloads SHALL identify whether embedding, VLM, and IndexTTS routes are disabled, local, external, degraded, incompatible, or unreachable as applicable and SHALL not expose credentials.

#### Scenario: External service is healthy
- **WHEN** a configured endpoint responds with expected model metadata
- **THEN** health reports the route as external and ready with the effective model identity

#### Scenario: Required local embedding profile is missing
- **WHEN** the internal embedding URL is selected but its profile-managed service is not running
- **THEN** health reports the route as local and unreachable with an actionable profile hint

#### Scenario: Optional IndexTTS is disabled
- **WHEN** no IndexTTS URL or profile is configured
- **THEN** health reports IndexTTS as disabled rather than unreachable

### Requirement: IndexTTS readiness proves model availability
The IndexTTS service SHALL distinguish lightweight process liveness from model readiness and SHALL return sanitized model/revision information suitable for local or shared routing decisions.

#### Scenario: Process is alive while model is loading
- **WHEN** the IndexTTS HTTP process accepts requests but the synthesis model is not ready
- **THEN** liveness succeeds and readiness remains unavailable

#### Scenario: Shared IndexTTS is ready
- **WHEN** model loading and a lightweight synthesis-capable probe succeed
- **THEN** readiness reports the served model and revision without returning secret paths or tokens

### Requirement: Shared services do not add public host ports
The deployment SHALL keep embedding, VLM, and IndexTTS off independent public host ports and SHALL use a private shared Docker network or authenticated nginx routes for cross-worktree access.

#### Scenario: Worktree shares a private GPU stack
- **WHEN** a worktree joins the documented shared Docker network
- **THEN** it reaches the GPU services through stable private aliases without publishing new host ports

#### Scenario: Service is exposed through nginx
- **WHEN** a GPU endpoint must be reachable outside its Docker network
- **THEN** nginx exposes it through the existing edge port with authentication and request limits

### Requirement: Optional-service failures remain isolated
An unavailable optional VLM or IndexTTS route SHALL not prevent unrelated application startup, and IndexTTS failure SHALL continue through Backend's configured TTS provider fallback chain.

#### Scenario: Local VLM profile is not running
- **WHEN** no external VLM URL or local VLM profile is configured
- **THEN** non-vision application features start normally and health reports VLM disabled

#### Scenario: Configured IndexTTS becomes unavailable
- **WHEN** an enabled local or external IndexTTS route fails during synthesis
- **THEN** Backend records the provider failure and attempts the next configured TTS provider

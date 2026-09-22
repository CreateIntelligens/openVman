## ADDED Requirements

### Requirement: Resource ownership is enforced by an authoritative registry
The system SHALL register every private project, Avatar character, background, mascot, and custom voice with one owner account and SHALL authorize resource operations by querying that registry, not by trusting a client-provided identifier.

#### Scenario: User guesses another account's resource ID
- **WHEN** an authenticated user requests or mutates a private resource owned by another account
- **THEN** the system returns 404 and performs no read, write, provider call, or cache lookup for that resource

#### Scenario: Owner accesses a private resource
- **WHEN** an authenticated owner requests their registered private resource
- **THEN** the operation proceeds using the server-resolved resource path and owner context

### Requirement: Administrator grants do not transfer resource ownership
The system SHALL allow an admin to grant a formal non-admin or temporary account access to selected projects／knowledge bases, Avatar characters, and voices while preserving the original resource owner and SHALL reject access to every ungranted resource in authenticated account selectors.

#### Scenario: Temporary account uses a granted resource
- **WHEN** a temporary account selects a project, character, or voice present in its grant rows
- **THEN** the resolver permits use while preserving the original owner context

#### Scenario: Temporary account guesses an ungranted resource
- **WHEN** a temporary account supplies an existing but ungranted project, persona, character, or voice ID
- **THEN** the system returns 404 before any Brain, filesystem, provider, or cache access

#### Scenario: Formal account selects an ungranted system-public resource
- **WHEN** a formal non-admin supplies an existing but ungranted character or voice ID
- **THEN** the system returns 404 before filesystem, provider, or cache access

#### Scenario: Grant is removed or account expires
- **WHEN** an admin removes the grant, revokes the account, or the 72-hour window expires
- **THEN** the next request loses access without changing or deleting the underlying resource

### Requirement: Project ownership scopes all Brain data
The system SHALL treat a project's owner as the owner of that project's knowledge workspace, personas, memory, sessions, LanceDB indexes, graph data, and project skills.

#### Scenario: Project list is account-scoped
- **WHEN** a normal user lists projects
- **THEN** the response includes only projects owned by or explicitly granted to that user

#### Scenario: Client supplies a foreign project to chat or search
- **WHEN** a normal user submits another account's `project_id` to chat, search, memory, session, persona, skill, or knowledge routes
- **THEN** the Backend rejects the request before forwarding it to Brain

### Requirement: Cross-service identity is trusted only from Backend
The system SHALL strip externally supplied internal identity headers, SHALL inject verified account and project context when proxying to Brain, and Brain SHALL require the configured internal token before accepting that context.

#### Scenario: Client forges an internal identity header
- **WHEN** an external request supplies `X-OpenVMan-User-ID`, role, or resolved-project headers
- **THEN** Backend discards those values and uses only the authenticated account context

#### Scenario: Brain receives no valid internal token
- **WHEN** a protected Brain route is called without the Backend internal token
- **THEN** Brain rejects the request without reading project data

### Requirement: Private media assets use account namespaces
The system SHALL store newly uploaded Avatar characters, backgrounds, mascots, and custom voice references below an account-specific directory and SHALL serve private files only through authenticated routes.

#### Scenario: Two accounts choose the same asset ID
- **WHEN** two accounts each upload a private asset with the same user-facing ID
- **THEN** both assets coexist in separate owner namespaces and each account sees only its own asset

#### Scenario: Private asset URL is fetched without a session
- **WHEN** an unauthenticated client requests a private character, image, model, or voice reference URL
- **THEN** the request returns 401 without streaming file bytes

### Requirement: System-public resources remain grantable and immutable to users
The system SHALL allow administrators to grant system-public resources without transferring ownership, SHALL prevent normal users from mutating them, and SHALL expose only complete system-public characters through the unauthenticated public Avatar SDK list.

#### Scenario: Public SDK lists characters
- **WHEN** an unauthenticated SDK client calls the public character list
- **THEN** the response includes complete system-public characters and excludes every private character

#### Scenario: User selects a system provider voice
- **WHEN** an authenticated user selects an allowed system-public provider voice
- **THEN** TTS uses that voice without granting mutation rights over its catalog entry

### Requirement: Custom voice synthesis is owner-scoped
The system SHALL resolve a custom voice to an owner-scoped opaque runtime key before calling IndexTTS and SHALL include owner scope and resolved voice identity in the TTS cache key.

#### Scenario: User synthesizes with their custom voice
- **WHEN** an owner requests TTS with one of their custom voices
- **THEN** Backend invokes IndexTTS with the resolved opaque voice key and caches audio only within that owner scope

#### Scenario: User supplies another account's custom voice ID
- **WHEN** a user requests TTS using another account's private voice ID
- **THEN** the system returns 404 before synthesis and does not return a cached result

### Requirement: HTTP, SSE, and WebSocket share authorization semantics
The system SHALL apply the same account, project, persona, character, and voice ownership checks regardless of whether a request uses HTTP, SSE, or WebSocket.

#### Scenario: WebSocket client changes capability IDs
- **WHEN** an authenticated client sends `client_init` with a foreign project, persona, character, or custom voice ID
- **THEN** the server rejects initialization and creates no live Brain or TTS session

### Requirement: Existing data is migrated without implicit sharing
The system SHALL provide an idempotent migration that assigns existing projects to the bootstrap admin, registers existing public media and IndexTTS speakers as system-public, and reports orphaned or ambiguous entries.

#### Scenario: Migration is run twice
- **WHEN** the same migration runs again after a successful run
- **THEN** ownership rows remain unchanged and no project or asset is duplicated or deleted

#### Scenario: Migration encounters an ambiguous asset
- **WHEN** an existing asset cannot be safely classified
- **THEN** the migration records it in the reconciliation report and does not expose it as private or system-public automatically

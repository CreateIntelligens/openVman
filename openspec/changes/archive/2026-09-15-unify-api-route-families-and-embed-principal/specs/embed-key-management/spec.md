## ADDED Requirements

### Requirement: Administrator embed-key API
The Backend SHALL provide `GET /api/v1/embed-keys`, `POST /api/v1/embed-keys`, `PATCH /api/v1/embed-keys/{key_id}`, and `DELETE /api/v1/embed-keys/{key_id}` for administrators. Keys SHALL be generated server-side as `ovk_` followed by 24 random base32 characters and returned in full on every read, since a key is a public identifier.

#### Scenario: Create a key
- **WHEN** an administrator posts a label, `project_id`, at least one allowed origin, and optional default character, persona, TTS provider, voice, `rate_limit_per_minute`, and `daily_request_quota`
- **THEN** the response contains the generated `key_id`, the stored fields, `disabled = false`, and creation defaults of 60 requests per minute and 1000 requests per day when limits are omitted

#### Scenario: Wildcard origin refused
- **WHEN** an administrator supplies `*` or an origin without a scheme
- **THEN** the response is 400 and no key is created

#### Scenario: Project must be accessible
- **WHEN** an administrator supplies a `project_id` that does not exist
- **THEN** the response is 404

#### Scenario: Revoke and edit
- **WHEN** an administrator deletes a key
- **THEN** subsequent requests with that key return 401
- **WHEN** an administrator patches origins, limits, defaults, label, or `disabled`
- **THEN** the change applies to the next request without restart

#### Scenario: Non-administrator
- **WHEN** a regular or temporary account calls any embed-key endpoint
- **THEN** the response is 403

### Requirement: Admin portal embed-key page
The Admin portal SHALL provide an "Embed Keys" page listing each key with its label, project, origins, limits, today's request count, and status, with actions to create, edit, disable, and delete keys.

#### Scenario: List shows usage
- **WHEN** an administrator opens the page
- **THEN** each row shows the key id, project label, allowed origins, limits, `requests_today`, and whether the key is disabled

#### Scenario: Create flow
- **WHEN** an administrator submits the create form
- **THEN** the new key appears in the list with its full `key_id` and a copy control

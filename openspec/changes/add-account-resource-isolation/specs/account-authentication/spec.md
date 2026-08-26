## ADDED Requirements

### Requirement: Account credentials create a revocable session
The system SHALL authenticate a normalized username and bcrypt password through `POST /api/auth/login`, SHALL return the same generic 401 response for an unknown username or invalid password, and SHALL refuse disabled accounts.

#### Scenario: Valid credentials create a session
- **WHEN** an enabled account submits valid credentials
- **THEN** the system returns the account profile and a signed session JWT
- **THEN** the system sets the JWT in the `openvman_session` HttpOnly cookie

#### Scenario: Invalid credentials do not disclose account existence
- **WHEN** a client submits either an unknown username or an invalid password
- **THEN** both requests return the same 401 status and error body

### Requirement: Session JWT uses a dedicated signing contract
The system SHALL sign session JWTs with HS256 using only the required `SESSION_JWT_SECRET`, and each token SHALL contain `sub`, `role`, `kind`, `ver`, `iat`, `exp`, `iss=openvman`, and `aud=openvman-web` claims.

#### Scenario: Signing secret is missing
- **WHEN** the service starts without `SESSION_JWT_SECRET`
- **THEN** auth initialization fails closed instead of using an API key or built-in fallback secret

#### Scenario: Token signature or audience is invalid
- **WHEN** a request carries a token with an invalid signature, issuer, audience, format, or expiry
- **THEN** the protected endpoint returns 401 without exposing token validation internals

### Requirement: Browser and API clients use safe token transports
The system SHALL accept an HttpOnly same-origin session cookie for browser requests and `Authorization: Bearer` for API clients, SHALL NOT accept session tokens from query parameters, and production cookies SHALL set `Secure`, `SameSite=Lax`, and `Path=/`.

#### Scenario: Browser restores a valid session
- **WHEN** a browser with a valid session cookie calls `GET /api/auth/me`
- **THEN** the system returns the current account profile without exposing the JWT to frontend JavaScript

#### Scenario: Frontend handles an expired session
- **WHEN** any shared frontend API request receives 401
- **THEN** the AuthProvider clears its account state and routes the user to the login screen
- **THEN** no JWT is read from or written to `localStorage`

### Requirement: Current account state is revalidated server-side
The system SHALL reload the account identified by `sub` for every authenticated request, SHALL use the current database role and disabled state, and SHALL compare JWT `ver` with the account `token_version`.

#### Scenario: Account is disabled after login
- **WHEN** an administrator disables an account that still has an unexpired JWT
- **THEN** the account's next protected request returns 401

#### Scenario: All sessions are revoked
- **WHEN** an account password changes or an administrator revokes all sessions
- **THEN** `token_version` increments and every older JWT returns 401

### Requirement: Cookie-authenticated mutations resist CSRF
The system SHALL require a same-origin `Origin` for state-changing requests authenticated by cookie and SHALL exempt a request only when it is authenticated exclusively by a valid Bearer token.

#### Scenario: Cross-origin cookie mutation is attempted
- **WHEN** a cross-origin site submits a state-changing request that relies on the user's session cookie
- **THEN** the system rejects the request before executing its handler

### Requirement: Authentication is fail-closed by default
The system SHALL require a valid session for every route unless the route is explicitly allowlisted as login, required health, frontend login assets, or a public Avatar SDK resource.

#### Scenario: A new route has no public declaration
- **WHEN** a client calls a newly added API route without a valid session
- **THEN** the route returns 401 by default

#### Scenario: User logs out
- **WHEN** an authenticated browser calls `POST /api/auth/logout`
- **THEN** the system clears the session cookie and subsequent protected requests return 401

### Requirement: Temporary credentials authenticate without a username
The system SHALL accept a generated temporary password through `POST /api/auth/temporary-login` without requiring or accepting a username, SHALL start its 72-hour lifetime on the first successful login, and SHALL never extend that lifetime on later logins.

#### Scenario: Temporary password is used for the first time
- **WHEN** a valid unused temporary password is submitted
- **THEN** the system atomically records `first_used_at` and `expires_at=first_used_at+72 hours`
- **THEN** the returned JWT expires no later than `expires_at`

#### Scenario: Active temporary password is reused
- **WHEN** the same valid password is submitted again before expiry
- **THEN** login succeeds with the original `first_used_at` and `expires_at`
- **THEN** the 72-hour window is not restarted or extended

#### Scenario: Temporary password is expired
- **WHEN** an expired temporary account logs in or calls any protected HTTP, SSE, or WebSocket route
- **THEN** the system returns 401 before allocating or reading a protected resource

### Requirement: Temporary sessions expose remaining lifetime safely
The system SHALL return `expires_at` and a non-negative `remaining_seconds` in temporary login and `/api/auth/me` profiles so the frontend can remind the user how long access remains.

#### Scenario: Temporary login succeeds
- **WHEN** the frontend receives a successful temporary login response
- **THEN** it displays the remaining duration and absolute expiry time
- **THEN** it does not store the password or JWT in localStorage

### Requirement: Admin portal access is explicitly authorized
The system SHALL allow ROOT and administrator accounts to enter the Admin portal, SHALL require an explicit `admin_portal_access` capability for formal non-admin and temporary accounts, and SHALL default that capability to false for existing and newly created scoped accounts.

#### Scenario: Scoped account has no Admin portal grant
- **WHEN** a formal non-admin or temporary session without `admin_portal_access` calls the Admin session bootstrap endpoint
- **THEN** the system returns 403 while leaving the session valid for the normal frontend

#### Scenario: Unauthorized temporary password is submitted to Admin login
- **WHEN** a valid unused temporary password without `admin_portal_access` is submitted to the Admin-specific temporary login endpoint
- **THEN** the system returns 403 without starting its 72-hour first-use window

#### Scenario: Scoped account receives an Admin portal grant
- **WHEN** an administrator enables `admin_portal_access` for a formal account or temporary batch
- **THEN** that account can bootstrap the Admin portal while retaining its existing resource scope

#### Scenario: Admin portal grant changes
- **WHEN** an administrator enables or disables `admin_portal_access`
- **THEN** the affected account sessions are revoked so the next request must reauthenticate against the current permission

## ADDED Requirements

### Requirement: The first administrator is created out of band
The system SHALL provide an idempotent container CLI for creating the first administrator with username `ai360` and password `ai360`, and SHALL NOT expose public account registration.

#### Scenario: Empty installation is bootstrapped
- **WHEN** an operator runs the `ai360` bootstrap command against an account database with no administrator
- **THEN** the command creates one enabled admin with a bcrypt password hash
- **THEN** the command never prints the plaintext password or JWT

#### Scenario: Bootstrap is repeated after an admin exists
- **WHEN** the bootstrap command is run after an administrator already exists
- **THEN** the command fails without creating or replacing an account

### Requirement: Administrators manage account lifecycle
The system SHALL allow an authenticated admin to list, create, enable, disable, and revoke sessions for accounts, while a normal user SHALL only read their own account profile.

#### Scenario: Admin creates an account
- **WHEN** an admin submits a unique username, valid password, and allowed role
- **THEN** the system creates the account and records the creating administrator

#### Scenario: Normal user attempts account administration
- **WHEN** a non-admin calls any account-management endpoint
- **THEN** the system returns 403 and performs no mutation

### Requirement: Administrators configure formal account resources
The system SHALL allow an authenticated admin to replace a formal non-admin account's project／knowledge-base, Avatar character, and voice grants plus accessible defaults, and SHALL source every selectable option from the authoritative resource registry.

#### Scenario: Admin limits a formal account
- **WHEN** an admin selects one project, one character, and one voice for a formal non-admin account
- **THEN** the account sees those grants plus private resources it owns
- **THEN** unselected system-public and private resources are not returned by authenticated selectors

#### Scenario: Runtime provider list differs from the registry
- **WHEN** a TTS provider is unavailable or reports a voice that is not registered
- **THEN** the account editor and temporary batch form still list only registered grantable voices
- **THEN** every selectable grant set passes backend resource validation

### Requirement: Account deletion preserves owned data safety
The system SHALL block deletion of an account that owns private resources and SHALL require those resources to be transferred or deleted first.

#### Scenario: Account still owns a project or private asset
- **WHEN** an admin attempts to delete that account
- **THEN** the system returns 409 with resource counts and leaves the account and resources unchanged

#### Scenario: Account owns no private resources
- **WHEN** an admin deletes a disabled account with no private resources
- **THEN** the account is removed and all of its outstanding JWTs cease to authenticate

### Requirement: Administrative invariants prevent lockout
The system SHALL prevent an admin from disabling or deleting their own active account and SHALL preserve at least one enabled administrator.

#### Scenario: Last enabled administrator would be removed
- **WHEN** an operation would disable or delete the final enabled administrator
- **THEN** the system rejects the operation without changing account state

### Requirement: Administrators generate temporary accounts in batches of five
The system SHALL add temporary-account generation to the existing Admin account page, SHALL create exactly five passwords per batch, and SHALL return each plaintext password only in the successful creation response.

#### Scenario: Admin generates a batch
- **WHEN** an admin submits valid knowledge-base, character, and voice grants
- **THEN** the system creates five temporary accounts with the same selected grants
- **THEN** the response contains five distinct random 12-character alphanumeric passwords and no later API can retrieve them

#### Scenario: Normal user attempts generation
- **WHEN** a non-admin calls the temporary batch endpoint
- **THEN** the system returns 403 and creates no account, password, or grant

### Requirement: Temporary accounts can be revoked and audited
The system SHALL list temporary account state without exposing password hashes, SHALL show unused／active／expired／revoked state and expiry metadata, and SHALL allow an admin to revoke remaining access immediately.

#### Scenario: Admin revokes an active temporary account
- **WHEN** an admin revokes a temporary account before its 72-hour expiry
- **THEN** its token version increments and all current or later requests return 401

#### Scenario: Admin lists a generated batch
- **WHEN** an admin views temporary accounts after the generation response is gone
- **THEN** state, grants, creator, first-use, and expiry remain visible
- **THEN** no plaintext password or password hash is returned

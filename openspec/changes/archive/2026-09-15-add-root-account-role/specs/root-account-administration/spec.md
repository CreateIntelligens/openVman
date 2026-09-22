## ADDED Requirements

### Requirement: The installation has exactly one protected ROOT account
The system SHALL persist `root` as a role above `admin` and `user`, SHALL display that role as `ROOT`, and SHALL reserve the single ROOT identity for the formal account whose normalized username is `ai360`.

#### Scenario: Existing installation is migrated
- **WHEN** schema migration finds the existing formal `ai360` account and no conflicting ROOT
- **THEN** it changes that account role to `root` without changing its ID, password hash, ownership, grants, defaults, or creation metadata
- **THEN** it increments token version so every pre-migration session is rejected

#### Scenario: Empty installation is bootstrapped
- **WHEN** the operator runs the supported bootstrap command against a database without ROOT
- **THEN** it creates the enabled `ai360` ROOT with a bcrypt hash for the supplied bootstrap password
- **THEN** repeating bootstrap cannot create or replace another ROOT

#### Scenario: Conflicting privileged state is detected
- **WHEN** migration or bootstrap detects another ROOT or a conflicting `ai360` identity
- **THEN** it fails without choosing, replacing, or silently demoting a privileged account

### Requirement: ROOT and administrator permissions follow a strict hierarchy
The system SHALL treat ROOT as authorized for every existing administrator capability, SHALL allow ROOT to manage admin／user／temporary accounts, and SHALL restrict administrators to managing user／temporary accounts.

#### Scenario: ROOT creates an administrator
- **WHEN** ROOT submits a valid unique formal account with role `admin`
- **THEN** the system creates the administrator and records ROOT as creator

#### Scenario: Administrator attempts to manage a privileged account
- **WHEN** an admin attempts to create an admin, change an admin, or mutate ROOT
- **THEN** the system returns 403 and performs no account, grant, session, or audit mutation

#### Scenario: ROOT uses an existing administrator route
- **WHEN** ROOT calls a resource or system-management route protected as administrator access
- **THEN** the request is authorized with the same full resource visibility as admin

### Requirement: ROOT identity cannot be changed through account administration
The system SHALL reject attempts through account-management APIs to create a second ROOT or to rename, disable, delete, demote, or replace the existing ROOT.

#### Scenario: ROOT targets itself with a destructive operation
- **WHEN** ROOT attempts to disable, delete, demote, or rename its own account
- **THEN** the system rejects the operation without changing ROOT state

#### Scenario: Any actor attempts to assign ROOT role
- **WHEN** an account create or role-change request contains role `root`
- **THEN** the system rejects the request and the unique ROOT remains unchanged

### Requirement: ROOT controls administrator and user role transitions
The system SHALL allow ROOT to promote a formal user to admin or demote an admin to user, SHALL forbid every other actor from privileged role changes, and SHALL revoke target sessions atomically with a successful role change.

#### Scenario: ROOT promotes a user
- **WHEN** ROOT changes a formal user role to admin
- **THEN** the role becomes admin, user-specific grants／defaults cease to apply, and every older target session returns 401

#### Scenario: ROOT demotes an administrator
- **WHEN** ROOT supplies role user with complete valid grants and defaults for an admin
- **THEN** the role and scoped access change atomically and every older target session returns 401

#### Scenario: Demotion lacks valid scoped access
- **WHEN** ROOT attempts to demote an admin without complete valid user grants and defaults
- **THEN** the system returns 422 and preserves the original role, access, and sessions

### Requirement: Password administration never reveals an existing password
The system SHALL store only bcrypt password hashes, SHALL provide no API or UI for reading plaintext passwords or password hashes, and SHALL allow ROOT to replace a lower account's password with a newly supplied valid password.

#### Scenario: ROOT resets a lower account password
- **WHEN** ROOT supplies a valid new password for an admin or formal user
- **THEN** the system stores a new bcrypt hash, increments token version, returns only a safe account profile, and rejects all previous sessions

#### Scenario: Any actor requests an existing password
- **WHEN** ROOT, admin, user, or an unauthenticated client requests an account's current password or hash
- **THEN** no endpoint or response provides it

#### Scenario: Administrator attempts privileged password reset
- **WHEN** an admin attempts to reset an admin or ROOT password
- **THEN** the system returns 403 and leaves credentials and sessions unchanged

#### Scenario: Temporary password creation response is gone
- **WHEN** ROOT later lists or audits a temporary account batch
- **THEN** the system returns state and grant metadata without plaintext credentials or hashes

### Requirement: Privileged account mutations are revocable and auditable
The system SHALL append an audit event in the same transaction as each privileged account mutation and SHALL exclude passwords, password hashes, JWTs, and temporary credentials from every audit field and log.

#### Scenario: ROOT mutates an administrator
- **WHEN** ROOT creates, changes role, resets password, disables, enables, revokes sessions, or deletes an administrator
- **THEN** one audit event records action, actor ID, target ID, timestamp, and non-secret metadata

#### Scenario: Mutation fails
- **WHEN** validation, hierarchy policy, ownership safety, or persistence rejects an account mutation
- **THEN** neither account state nor a success audit event is committed

### Requirement: Admin frontend exposes only authorized ROOT operations
The Admin frontend SHALL recognize `root`, show it as `ROOT`, grant it every existing admin page, and render account mutation controls according to the authenticated actor and target hierarchy.

#### Scenario: ROOT opens account management
- **WHEN** authenticated `ai360` ROOT opens the account page
- **THEN** it can create admins and users and can access role-change, password-reset, disable, session-revoke, and delete controls for permitted lower accounts
- **THEN** its own protected operations remain unavailable

#### Scenario: Administrator opens account management
- **WHEN** an admin opens the same page
- **THEN** user／temporary management remains available while ROOT and admin mutation controls are absent

#### Scenario: Frontend receives a server denial
- **WHEN** stale frontend state exposes an operation that Backend rejects
- **THEN** the page reports the error and does not optimistically retain an unauthorized state change

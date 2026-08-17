## ADDED Requirements

### Requirement: Temporary passwords are random 12-character codes and non-recoverable
The system SHALL generate each temporary password as exactly 12 random alphanumeric characters, SHALL use its first four characters as a non-secret lookup locator, SHALL store only a bcrypt hash plus that locator, and SHALL never write plaintext temporary passwords to logs or persistent storage.

#### Scenario: Batch creation is persisted
- **WHEN** five temporary passwords are generated
- **THEN** database rows contain hashes and locators but none of the five plaintext values

#### Scenario: Password response is lost
- **WHEN** the admin closes or refreshes the one-time result view
- **THEN** the system requires generating a new batch instead of recovering the old plaintext passwords

### Requirement: Temporary access uses a hard 72-hour first-use window
The system SHALL begin the lifetime only on the first successful password verification, SHALL retain the original expiry across later logins, and SHALL revalidate expiry on every request.

#### Scenario: Unused credential waits before distribution
- **WHEN** a generated password is not used for any length of time
- **THEN** it remains unused with no running expiry countdown until disabled, deleted, or first used

#### Scenario: Concurrent first use occurs
- **WHEN** two correct login attempts race on an unused password
- **THEN** exactly one transaction establishes the first-use timestamp and both successful sessions share the same expiry

### Requirement: Batch grants define the temporary account capability set
The system SHALL attach selected project／knowledge-base, character, and voice grants to every account in the generated batch, SHALL record an accessible default for each resource category, and SHALL obtain selectable grants from the same authoritative registry endpoint used by formal account administration.

#### Scenario: Default selections are available
- **WHEN** the selected grants include `proj-b85afb8bb6`, character `0713`, and IndexTTS voice `hayley`
- **THEN** the account opens with 創造智能醫院衛教助理, ESG-AIKKA雀斑, and Hayley selected

#### Scenario: Configured fallback is not granted
- **WHEN** a temporary account lacks one of the system fallback resources
- **THEN** the Backend returns the first explicitly granted resource as that category's default
- **THEN** the frontend does not retain an inaccessible local selection

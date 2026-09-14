## ADDED Requirements

### Requirement: Temporary passwords can be retrieved by account managers
The system SHALL generate each temporary password as exactly 20 random alphanumeric characters, SHALL use its first 12 characters as a private lookup locator, and SHALL retain bcrypt hashes for login verification. New batches SHALL additionally persist account-bound encrypted passwords for ROOT/admin retrieval, without storing plaintext in the database or logs.

#### Scenario: Batch creation is persisted
- **WHEN** five temporary passwords are generated
- **THEN** database rows contain hashes, private locators, and authenticated ciphertext but none of the five plaintext values

#### Scenario: Administrator reloads batch history
- **WHEN** ROOT or admin queries batch history after a refresh or backend restart
- **THEN** each new account exposes its original login password and the UI offers copying, with a no-store response
- **THEN** ordinary or temporary users cannot retrieve batch history even with portal access

#### Scenario: Legacy password or encryption key is unavailable
- **WHEN** a row has no saved ciphertext or its ciphertext cannot be decrypted
- **THEN** history returns a null password and the UI displays 密碼未保存 without showing the internal tmp account name
- **THEN** existing bcrypt-based login and expiry behavior remains unchanged

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

## ADDED Requirements

### Requirement: Portal accounts can edit granted project content
The system SHALL allow a formal non-admin or temporary account to modify project-scoped knowledge, Quick QA, Persona prompts, memories, project Skills, and project Tools only when the account has both `admin_portal_access` and an explicit grant for that project.

#### Scenario: Portal user edits granted knowledge
- **WHEN** a non-admin account with Admin portal access and a grant for project A saves or uploads knowledge in project A
- **THEN** the Backend forwards the mutation using project A's trusted context
- **THEN** the operation succeeds without granting access to any other project

#### Scenario: Portal user edits a Persona prompt
- **WHEN** a non-admin account with Admin portal access and a grant for project A updates a Persona prompt in project A
- **THEN** the Backend authorizes the project content edit and forwards it to Brain

#### Scenario: Granted account has no portal access
- **WHEN** a non-admin account has a grant for project A but does not have `admin_portal_access`
- **THEN** project content mutations are rejected without forwarding them to Brain or Gateway processing

### Requirement: Project grants remain fail-closed
The system SHALL return 404 and perform no project read or write when a portal account supplies an ungranted project identifier.

#### Scenario: Portal user targets an ungranted project
- **WHEN** a portal-enabled non-admin account sends a content mutation for project B without a project B grant
- **THEN** the Backend returns 404 before accessing Brain, files, indexes, caches, or provider services

#### Scenario: Project grant is revoked
- **WHEN** an administrator removes a portal account's project grant
- **THEN** the account's next read or content mutation for that project is rejected

### Requirement: Portal editing does not grant administrative lifecycle access
The system SHALL reserve account administration and project creation or deletion for `admin` and `root` roles, regardless of `admin_portal_access`, project ownership, or project grants.

#### Scenario: Portal user attempts account administration
- **WHEN** a portal-enabled non-admin account calls an account management endpoint
- **THEN** the Backend returns 403 and does not modify any account

#### Scenario: Portal user attempts to create a project
- **WHEN** a portal-enabled non-admin account calls the project creation endpoint
- **THEN** the Backend returns 403 and creates no Brain workspace or resource record

#### Scenario: Portal user attempts to delete a project
- **WHEN** a portal-enabled non-admin account calls the project deletion endpoint for an owned or granted project
- **THEN** the Backend returns 403 and preserves the project workspace and resource record

### Requirement: Global resource grants remain usage-only
The system SHALL NOT interpret Admin portal access as mutation permission for granted Avatar characters, backgrounds, mascots, or custom voices.

#### Scenario: Portal user targets a granted global asset
- **WHEN** a portal-enabled non-admin account attempts to modify a granted Avatar or voice resource it does not own
- **THEN** the Backend rejects the mutation while continuing to permit its authorized use

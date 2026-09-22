## 1. Authorization Model

- [x] 1.1 Add a project-content edit access level and allow explicit project grants to satisfy it only when `admin_portal_access` is enabled.
- [x] 1.2 Add resolver tests for portal-enabled edits, portal-disabled denials, ungranted projects, and unchanged global-resource mutation denial.

## 2. Backend Route Boundaries

- [x] 2.1 Classify Brain knowledge, Persona, memory-maintenance, Skill, and Tool mutations as project-content edits.
- [x] 2.2 Apply the same project-content edit authorization to Gateway knowledge uploads.
- [x] 2.3 Restrict project creation and deletion endpoints to `admin`／`root` while preserving scoped project listing and reads.
- [x] 2.4 Add route tests covering granted portal edits, denied ungranted edits, and denied non-admin project lifecycle operations.

## 3. Admin Portal Experience

- [x] 3.1 Update account-access copy to explain that portal access permits editing granted projects without account or project-lifecycle administration.
- [x] 3.2 Hide project creation and deletion controls from non-admin portal accounts while keeping granted project content editors available.
- [x] 3.3 Add Admin frontend tests for the revised capability copy and project lifecycle visibility.

## 4. Verification

- [x] 4.1 Run focused Backend authorization and route tests in containers.
- [x] 4.2 Run focused Admin tests and the production frontend build in the Admin development container.
- [x] 4.3 Run `openspec validate allow-portal-project-editing --strict` and `git diff --check`.

## 1. ROOT Schema and Migration

- [x] 1.1 Add failing migration tests from the current two-role schema covering preserved account IDs／hashes／resources, ai360 promotion, token-version increment, single-ROOT uniqueness, rerun safety, and conflicting privileged state.
- [x] 1.2 Extend `AccountRole` with `root` and add centralized role-rank／at-least-admin helpers used instead of direct admin equality checks.
- [x] 1.3 Add the SQLite users-table rebuild migration, partial unique ROOT index, foreign-key validation, and existing ai360 in-place promotion.
- [x] 1.4 Update bootstrap repository／CLI behavior and tests so an empty installation creates only the `ai360` ROOT and never replaces or creates a second ROOT.

## 2. Backend Authorization Hierarchy

- [x] 2.1 Add `require_root` and update `require_admin` so ROOT inherits all existing administrator routes without widening user or temporary-account access.
- [x] 2.2 Add a centralized actor／target account-management policy with ROOT→admin／user／temporary and admin→user／temporary test matrices.
- [x] 2.3 Enforce hierarchy on account list, create, enable／disable, session revoke, delete, resource-access update, and temporary batch routes; prohibit every destructive ROOT mutation.
- [x] 2.4 Replace direct `AccountRole.ADMIN` authorization comparisons across Backend resource selectors, static assets, admin routes, gateways, and Brain proxy context with the centralized hierarchy helper.

## 3. ROOT Account Operations and Audit

- [x] 3.1 Add failing API／repository tests for ROOT creating and managing admins, admin denials, unique ROOT protection, and safe error responses.
- [x] 3.2 Implement ROOT-only admin↔user role changes with atomic grants／defaults validation, user-grant cleanup on promotion, and target token-version revocation.
- [x] 3.3 Implement ROOT-only lower-account password reset using existing password validation／bcrypt, returning no plaintext or hash and invalidating every prior target session.
- [x] 3.4 Add append-only auth audit schema／repository records for privileged mutations, commit them atomically, and add redaction tests proving passwords, hashes, JWTs, and temporary credentials never enter audit or logs.
- [x] 3.5 Add operator-only ROOT password recovery that requires container access, never prints credentials, and cannot rename, replace, or create another ROOT.

## 4. Session and Resource Safety

- [x] 4.1 Extend JWT encode／decode／server-side revalidation tests for root claims, stale pre-migration claims, role changes, disabled targets, and token-version mismatch.
- [x] 4.2 Verify ROOT receives full registered project／knowledge-base, character, mascot, background, and voice access while admin and scoped account behavior remains unchanged.
- [x] 4.3 Run temporary-account creation／audit／revocation tests as ROOT and admin and prove neither can retrieve credentials after the one-time creation response.
- [x] 4.4 Add account-deletion ownership and last-privileged-account regressions so ROOT hierarchy does not weaken private-resource safety.

## 5. Admin Frontend

- [x] 5.1 Extend auth API types, session context, route gating, navigation, mocks, and tests to accept `root` and treat it as at least admin.
- [x] 5.2 Update the Accounts page to label ai360 as `ROOT`, let ROOT create／manage admins and users, and hide privileged controls from admin and self-destructive controls from ROOT.
- [x] 5.3 Add ROOT role-change and password-reset dialogs with password fields that are never prefilled, retained after success, logged, or rendered as existing credentials.
- [x] 5.4 Add frontend behavior tests for ROOT／admin operation matrices, reset success／failure, server-denial recovery, and absence of password／hash fields in account responses.

## 6. Verification and Rollout

- [x] 6.1 Update account administration／deployment documentation with the three-level hierarchy, ai360 migration, immediate production password-change guidance, reset-not-read semantics, and rollback backup requirement.
- [x] 6.2 Run focused auth repository／API／migration／resource tests, full Backend regressions, Admin TypeScript／Vitest／production build, and strict OpenSpec validation.
- [x] 6.3 Exercise a copied current auth database through migration and rollback rehearsal, verifying row counts, foreign keys, ai360 ROOT login, old-session rejection, admin denials, ROOT audit events, and unchanged owned resources.
- [x] 6.4 Verify in a real browser that ROOT sees all permitted account actions, admin cannot mutate privileged accounts, user has no account administration, and no interface exposes existing passwords.

## 1. Brain Provider Configuration

- [x] 1.1 Add dedicated NEN key and base-URL settings and resolve `nen` routes independently from OpenAI
- [x] 1.2 Add focused tests for NEN defaults, route construction, provider order, and OpenAI coexistence

## 2. Deployment Configuration

- [x] 2.1 Forward NEN settings through Docker Compose
- [x] 2.2 Migrate the local environment to Gemini primary with NEN as the final explicit fallback

## 3. Documentation and Verification

- [x] 3.1 Update `.env.example`, Brain documentation, detailed Brain specification, and `CHANGELOG.md`
- [x] 3.2 Run focused Brain tests, OpenSpec validation, `git diff --check`, and inspect the complete dirty-tree scope

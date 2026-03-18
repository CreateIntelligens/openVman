## 1. Skill System Foundation

- [x] 1.1 Define `Skill` and `SkillManifest` models in `brain/api/tools/skill.py`
- [x] 1.2 Implement `SkillManager` for scanning and validation in `brain/api/tools/skill_manager.py`
- [x] 1.3 Update `ToolRegistry` to support dynamic tool registration and skill binding

## 2. Discovery and Loading

- [x] 2.1 Implement skill package discovery in `brain/skills/`
- [x] 2.2 Add manifest validation (required fields, tool schemas)
- [x] 2.3 Implement lazy loading of skill implementation modules

## 3. Integration and Implementation

- [x] 3.1 Create an `example-skill` to verify discovery and tool registration
- [x] 3.2 Update `ChatService` or `agent_loop` to ensure skill tools are included in LLM context
- [x] 3.3 Ensure namespacing of tools (prefixed with skill ID)

## 4. Testing and Verification

- [x] 4.1 Add unit tests for `SkillManager` and `Skill` models
- [x] 4.2 Add integration tests verifying LLM tool calls to skill-provided tools
- [x] 4.3 Verify error handling for malformed skills or failed tool executions

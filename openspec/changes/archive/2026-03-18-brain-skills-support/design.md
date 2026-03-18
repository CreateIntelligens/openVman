## Context

The current `ToolRegistry` in the brain is a static registry populated during startup. It doesn't support logical grouping of tools or dynamic extension without modifying core code. Brian has requested a "Skills" feature to allow future flexibility and easier integration of third-party capabilities.

## Goals / Non-Goals

**Goals:**
- **Modular Skills**: Group related tools and logic into "Skill" packages.
- **Dynamic Discovery**: Automatically discover and load skills from a `brain/skills/` directory.
- **Manifest-driven**: Use a manifest file (e.g., `skill.yaml`) to define skill metadata and requirements.
- **Tool Integration**: Skills should be able to register their own tools into the global `ToolRegistry`.

**Non-Goals:**
- **Remote Skill Installation**: We won't support downloading skills from a remote repository in this initial phase.
- **Versioning/Dependency Resolution**: While manifesting versions is good, complex resolution is out of scope.

## Decisions

1. **Skill Directory Structure**:
   - `brain/skills/<skill-id>/`
   - `brain/skills/<skill-id>/skill.yaml` (Manifest)
   - `brain/skills/<skill-id>/main.py` (Implementation)

2. **Manifest Format**:
   - `id`: Unique kebab-case identifier.
   - `name`: Human-readable name.
   - `description`: What the skill does.
   - `tools`: List of tool definitions provided by this skill.

3. **Loading Mechanism**:
   - A `SkillManager` will scan the `skills/` directory.
   - It will load the manifest and import the implementation.
   - It will register tools via an extension to `ToolRegistry`.

## Risks / Trade-offs

- [Risk] Namespace collisions for tools. → [Mitigation] Enforce skill-prefixed tool names (e.g., `weather:get_forecast`).
- [Risk] Initialization overhead. → [Mitigation] Lazy-load skill implementations when a tool from that skill is first called.

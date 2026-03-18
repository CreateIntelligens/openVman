## Why

Currently, the brain's "tools" are hardcoded within the `ToolRegistry`, which makes it difficult to extend the system with new capabilities without modifying core files. Brian has requested a "Skills" feature to allow for modular extension. This change introduces a plugin-like system where "Skills" can be developed as independent packages, making the brain more flexible and future-proof for various use cases (e.g., weather, calendar, CRM integrations).

## What Changes

- **Skill Abstraction**: Define a standard `Skill` interface that bundles related tools, prompts, and configuration.
- **Dynamic Loading**: Implement a mechanism to discover and load skill packages from a dedicated `brain/skills/` directory.
- **Skill Registry**: Add a `SkillRegistry` to manage the lifecycle and state of loaded skills.
- **Enhanced Tool Registry**: Update the existing `ToolRegistry` to integrate tools provided by active skills.
- **Skill Manifest**: Define a `skill.yaml` or similar manifest format for skill metadata.

## Capabilities

### New Capabilities
- `skill-system`: Core infrastructure for discovering, validating, and loading skill packages.
- `skill-tool-provider`: Integration layer that allows skills to register tools into the global `ToolRegistry`.

### Modified Capabilities
- `tool-registry`: Update to support dynamic tool registration from external skill providers.

## Impact

- **Backend/Brain API**: New service/module for skill management.
- **File System**: New `brain/skills/` directory for skill packages.
- **Configuration**: New environment variables for skill search paths and enabled skills.
- **Extensibility**: Developers can now add new features to the brain without PRing into the core tool registry.

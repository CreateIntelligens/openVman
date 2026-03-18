## ADDED Requirements

### Requirement: skill-discovery
The system MUST be able to discover skill packages within a configured directory.

#### Scenario: Discover valid skill
- **WHEN** a subdirectory containing a valid `skill.yaml` exists in `brain/skills/`
- **THEN** the system should include it in the list of available skills.

#### Scenario: Ignore invalid skill
- **WHEN** a subdirectory exists but lacks a `skill.yaml` or has a malformed one
- **THEN** the system should log a warning and skip the directory.

### Requirement: dynamic-tool-registration
Skills MUST be able to contribute tools to the brain's toolset.

#### Scenario: Register tools from skill
- **WHEN** a skill is loaded and it defines tools in its manifest
- **THEN** those tools should be available for the LLM to call via the `ToolRegistry`.

#### Scenario: Tool name namespacing
- **WHEN** a skill registers a tool
- **THEN** the tool name should be prefixed with the skill ID to prevent collisions.

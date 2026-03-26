## ADDED Requirements

### Requirement: core-architecture-overview
The document must provide a unified view of the openVman system, describing the roles of the Frontend (Sensory Layer), Backend (Nervous System), Brain (Cognitive Core), and Gateway (External Sensory Layer).

#### Scenario: initial-draft
- **WHEN** reading the document
- **THEN** it should clearly state the "Core Philosophy" of decoupling nervous system and cognitive core.

### Requirement: component-interaction-diagram
The document must include a high-level diagram (Mermaid) showing how data flows between the four main components.

#### Scenario: data-flow-visibility
- **WHEN** looking at the diagram
- **THEN** user should see how a user utterance from Frontend reaches the Brain and returns as speech.

# admin-theming Specification

## Purpose
Enable users to switch between Light Mode and Dark Mode in the Admin Web interface to improve accessibility and user comfort.

## ADDED Requirements

### Requirement: Theme Selection state
The system SHALL maintain a global theme state that can be toggled between "light" and "dark".

#### Scenario: Initial State
- **WHEN** the user first visits the admin portal
- **THEN** the system defaults to "dark" mode but checks for a saved preference in `localStorage`.

### Requirement: Theme Toggle UI
The system SHALL provide a visible toggle component in the sidebar to switch themes.

#### Scenario: Toggling Theme
- **WHEN** the user clicks the "Theme Toggle" button
- **THEN** the system immediately updates the `<html>` class (adding/removing `dark`) and persists the new setting to `localStorage`.

### Requirement: Responsive Styling
The system SHALL use theme-aware CSS classes to ensure all UI elements adapt correctly to the selected mode.

#### Scenario: Light Mode Appearance
- **WHEN** "light" mode is active
- **THEN** the background should be light (e.g., `bg-slate-50` or `bg-white`) and text should be dark (e.g., `text-slate-900`), while maintaining brand colors (primary purple).

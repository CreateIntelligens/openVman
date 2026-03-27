## Why

The current admin web interface is locked to Dark Mode. Users have reported that the interface feels too dark for extended use in certain environments. Adding a Light Mode (平常模式) option will improve accessibility, user comfort, and align with standard UI best practices for professional dashboards.

## What Changes

- **Theme Switching Mechanism**: Introduce a global theme state (Light/Dark) managed via a React context or state.
- **Tailwind Refactoring**: Update hardcoded slate and background colors in `App.tsx`, `index.css`, and various page components to use Tailwind CSS `dark:` utilities or CSS variables.
- **Theme Toggle UI**: Add a prominent theme toggle button in the sidebar or header to allow users to switch between "平常模式" (Light) and "深色模式" (Dark).
- **Persistence**: Save the user's theme preference in `localStorage` to ensure it persists across sessions.
- **Default State**: Keep Dark Mode as the default to avoid jarring changes for current users, but provide an easy one-click switch.

## Capabilities

### New Capabilities
- `admin-theming`: Provides theme switching and persistence across the admin web interface.

### Modified Capabilities
- (None)

## Impact

- **Frontend Core**: `App.tsx` and `index.css` will be modified to support theme-aware classes.
- **UI Components**: Components using hardcoded dark colors (e.g., `KnowledgeBaseAdmin.tsx`, `Chat.tsx`) will need styling updates.
- **User Experience**: Users will have more control over the visual presentation of the tool.

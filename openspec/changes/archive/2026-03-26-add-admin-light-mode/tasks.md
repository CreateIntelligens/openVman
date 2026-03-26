## 1. Theme Foundation

- [x] 1.1 Update `App.tsx` to manage theme state (`light` | `dark`) with `localStorage` persistence.
- [x] 1.2 Implement side effect to toggle `dark` class on `document.documentElement`.
- [x] 1.3 Ensure `index.html` doesn't have a hardcoded `class="dark"` that overrides JS logic (or handle it in `App.tsx`).

## 2. Layout & Sidebar Refactoring

- [x] 2.1 Update `App.tsx` sidebar styles: replace hardcoded `bg-slate-900`, `bg-background-dark/95`, and `text-slate-400` with theme-aware classes.
- [x] 2.2 Update `index.css`: make scrollbars and custom selects (`select-dark`) adaptive to light mode.
- [x] 2.3 Update Main Content background: change `bg-background` to `bg-slate-50 dark:bg-background`.

## 3. Page & Component Styling

- [x] 3.1 `Chat.tsx`: Update message bubbles (`bg-slate-900/80` -> `bg-white dark:bg-slate-900/80`) and header/input area.
- [x] 3.2 `KnowledgeBaseAdmin.tsx`: Update file tree and editor pane backgrounds and borders.
- [x] 3.3 Generic Pages: Audit `Personas.tsx`, `Memory.tsx`, `Projects.tsx`, etc., and replace hardcoded dark colors with `dark:` variants.

## 4. Theme Toggle UI

- [x] 4.1 Create a `ThemeToggle` component or add it directly to `App.tsx` sidebar footer.
- [x] 4.2 Use `light_mode` / `dark_mode` icons and ensure tooltips/labels are correct.

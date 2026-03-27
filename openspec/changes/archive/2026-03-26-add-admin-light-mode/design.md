## Context

The `openVman` admin web currently uses a hardcoded dark theme. The `index.html` has a fixed `dark` class on the `<html>` tag, and most components use specific dark-themed Tailwind classes (e.g., `bg-slate-900`, `text-slate-200`) without light-mode counterparts.

## Goals / Non-Goals

**Goals:**
- Provide a "Light Mode" (平常模式) that feels professional and readable.
- Enable theme persistence using `localStorage`.
- Ensure a smooth transition between modes without page reloads.

**Non-Goals:**
- Automatic theme switching based on system OS (keep it user-manual for now).
- Multiple color themes (e.g., "blue mode", "high contrast"). Only Light/Dark.

## Decisions

- **Theme Control**: The theme will be controlled by adding/removing the `dark` class on the root `<html>` element. Tailwind's `darkMode: "class"` configuration is already in place.
- **Color Mapping**: 
  - Standard backgrounds will move from `bg-slate-950` to `bg-slate-50 dark:bg-slate-950`.
  - Content containers will move from `bg-slate-900` to `bg-white dark:bg-slate-900`.
  - Primary text will move from `text-slate-100` to `text-slate-900 dark:text-slate-100`.
- **Theme Toggle Location**: A new icon button will be added to the bottom of the Sidebar (near the "Pin" button) using Material Symbols (`light_mode` / `dark_mode`).
- **Initial Load Logic**: A small script in `index.html` or `App.tsx`'s `useEffect` will check `localStorage` and apply the theme before the first paint to avoid flickering.

## Risks / Trade-offs

- **Risk**: Hardcoded `slate` colors in deep components (like Chat bubbles or Code previews) might be missed, leading to poor contrast in light mode.
- **Trade-off**: Using `dark:` variants for every color is more verbose than using purely CSS variables, but it's more idiomatic for this project's current Tailwind setup.

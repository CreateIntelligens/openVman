/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        slate: {
          50: "#faf9f7",
          100: "#f4f2ee",
          200: "#e7e4de",
          300: "#d3cec5",
          400: "#a9a298",
          500: "#7a7469",
          600: "#56524a",
          700: "#3d3a34",
          800: "#282622",
          900: "#1c1a17",
          950: "#151311",
        },
        primary: {
          DEFAULT: "rgb(var(--color-accent) / <alpha-value>)",
          50: "rgb(var(--color-accent-50) / <alpha-value>)",
          100: "rgb(var(--color-accent-100) / <alpha-value>)",
          500: "rgb(var(--color-accent-500) / <alpha-value>)",
          600: "rgb(var(--color-accent-600) / <alpha-value>)",
          700: "rgb(var(--color-accent-700) / <alpha-value>)",
        },
        surface: {
          DEFAULT: "rgb(var(--color-surface) / <alpha-value>)",
          sunken: "rgb(var(--color-surface-sunken) / <alpha-value>)",
          raised: "rgb(var(--color-surface-raised) / <alpha-value>)",
          overlay: "rgb(var(--color-surface-overlay) / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--color-border) / <alpha-value>)",
          strong: "rgb(var(--color-border-strong) / <alpha-value>)",
        },
        content: {
          DEFAULT: "rgb(var(--color-content) / <alpha-value>)",
          muted: "rgb(var(--color-content-muted) / <alpha-value>)",
          subtle: "rgb(var(--color-content-subtle) / <alpha-value>)",
          inverse: "rgb(var(--color-content-inverse) / <alpha-value>)",
        },
        success: "rgb(var(--color-success) / <alpha-value>)",
        warn: "rgb(var(--color-warn) / <alpha-value>)",
        danger: "rgb(var(--color-danger) / <alpha-value>)",
        info: "rgb(var(--color-info) / <alpha-value>)",
        "background-dark": "rgb(var(--color-surface) / <alpha-value>)",
      },
      fontFamily: {
        display: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1.4" }],
        sm: ["0.875rem", { lineHeight: "1.5" }],
        base: ["1rem", { lineHeight: "1.6" }],
        lg: ["1.125rem", { lineHeight: "1.5" }],
        xl: ["1.25rem", { lineHeight: "1.3" }],
        "2xl": ["1.5rem", { lineHeight: "1.2" }],
        "3xl": ["1.875rem", { lineHeight: "1.2" }],
      },
      borderRadius: {
        sm: "0.375rem",
        md: "0.5rem",
        lg: "0.75rem",
        xl: "1rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        xs: "0 1px 1px 0 rgb(0 0 0 / 0.04)",
        sm: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        md: "0 2px 6px -1px rgb(0 0 0 / 0.08)",
        lg: "0 8px 24px -6px rgb(0 0 0 / 0.12)",
      },
      maxWidth: {
        prose: "48rem",
      },
    },
  },
  plugins: [],
};

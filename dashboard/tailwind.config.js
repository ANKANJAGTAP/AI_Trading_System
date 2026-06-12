/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "var(--ink)",
        surface: "var(--surface)",
        "surface-raised": "var(--surface-raised)",
        "surface-inset": "var(--surface-inset)",
        line: "var(--line)",
        "line-strong": "var(--line-strong)",
        "text-hi": "var(--text-hi)",
        "text-lo": "var(--text-lo)",
        "text-faint": "var(--text-faint)",
        brand: "var(--brand)",
        long: "var(--long)",
        short: "var(--short)",
        warn: "var(--warn)",
        info: "var(--info)",
        "mode-sim": "var(--mode-sim)",
        "mode-live": "var(--mode-live)",
      },
      fontFamily: {
        ui: ["Geist", "Inter", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { panel: "6px", control: "4px", chip: "3px" },
      fontSize: {
        micro: ["10px", "14px"],
        eyebrow: ["11px", "14px"],
        dense: ["12px", "16px"],
      },
    },
  },
  plugins: [],
};

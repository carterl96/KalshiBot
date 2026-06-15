import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#0b0e14",
          soft: "#0f131b",
          card: "#141925",
          hover: "#1a2031",
        },
        line: "#222a3a",
        muted: "#7b8499",
        text: "#e6e9f0",
        pos: "#22c55e",
        neg: "#ef4444",
        accent: "#3b82f6",
        paper: "#f59e0b",
        live: "#ef4444",
      },
      fontFamily: {
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;

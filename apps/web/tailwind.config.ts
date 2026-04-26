import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        depth: {
          black: "#0A0A0A",
          surface: "#141414",
          panel: "#1C1C1C",
          line: "#2A2A2A",
          gold: "#E8D5A3",
          text: "#F5F5F5",
          muted: "#888888",
        },
      },
      fontFamily: {
        sans: ["Geist", "DM Sans", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;

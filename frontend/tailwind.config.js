/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // semantic flag colours used by the matrix grid
        flag: {
          green: "#16a34a",
          "green-bg": "#dcfce7",
          red: "#dc2626",
          "red-bg": "#fee2e2",
          grey: "#737373",
          "grey-bg": "#f5f5f5",
          mixed: "#a16207",
          "mixed-bg": "#fef3c7",
          empty: "#cbd5e1",
          "empty-bg": "#f1f5f9",
        },
        ink: {
          DEFAULT: "#111827",
          mute: "#6b7280",
          line: "#e5e7eb",
        },
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "Inter", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

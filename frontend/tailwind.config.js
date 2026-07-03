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
          blue: "#2563eb",
          "blue-bg": "#dbeafe",
          mixed: "#a16207",
          "mixed-bg": "#fef3c7",
          empty: "#cbd5e1",
          "empty-bg": "#f1f5f9",
        },
        // warm "paper" ink + hairline (editorial direction, harvested from Stitch tokens)
        ink: {
          DEFAULT: "#1c1b1b",
          mute: "#5d5f5d",
          line: "#e7e3e0",
        },
        canvas: "#fdf8f8",
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        display: ["Fraunces", "Georgia", "serif"], // editorial-сериф для крупных цифр матрицы
      },
    },
  },
  plugins: [],
};

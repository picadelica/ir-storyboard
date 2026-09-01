/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./studio/index.html", "./classic/index.html", "./src/**/*.{ts,tsx}", "./src-classic/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // semantic flag colours used by the matrix grid
        flag: {
          green: "#6f9723",
          "green-bg": "#eef7d5",
          red: "#d8644f",
          "red-bg": "#fae7df",
          grey: "#8a8d86",
          "grey-bg": "#f3f4ef",
          blue: "#4f95d8",
          "blue-bg": "#e4f1ff",
          mixed: "#a06b10",
          "mixed-bg": "#fff0cf",
          empty: "#d9dbd4",
          "empty-bg": "#f7f8f3",
        },
        // warm "paper" ink + hairline (editorial direction, harvested from Stitch tokens)
        ink: {
          DEFAULT: "#20221f",
          mute: "#70736d",
          line: "#dedfd8",
        },
        canvas: "#f6f6f1",
      },
      borderRadius: {
        sm: "8px",
        DEFAULT: "12px",
        md: "14px",
        lg: "16px",
        xl: "20px",
        "2xl": "22px",
        full: "9999px",
      },
      fontFamily: {
        sans: ["Arial", "Helvetica", "-apple-system", "BlinkMacSystemFont", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        display: ["Arial", "Helvetica", "sans-serif"],
      },
    },
  },
  plugins: [],
};

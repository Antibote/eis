/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: { xs: ["11.5px", "16px"], sm: ["13px", "19px"], base: ["14px", "21px"] },
      colors: {
        canvas: "#F4F5F7",
        surface: "#FFFFFF",
        line: "#DCE0E5",
        ink: { DEFAULT: "#1A1E24", soft: "#4A5260", faint: "#7A8290" },
        navy: { 50: "#EEF2F7", 100: "#D9E2EE", 500: "#2F5A8A", 600: "#244A75", 700: "#1C3A5E", 800: "#152C47", 900: "#0F2034" },
        graphite: { 700: "#2E333B", 800: "#23272D", 900: "#1A1D22" },
        crit: "#B42318", high: "#C4320A", med: "#B54708", low: "#667085",
        ok: "#067647", warn: "#B54708",
      },
      borderRadius: { DEFAULT: "4px", md: "5px", lg: "6px" },
    },
  },
  plugins: [],
};

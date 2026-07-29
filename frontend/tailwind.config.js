/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#234649",
        shell: "#f7f7f5",
        card: "#fcfbf8",
        brand: "#0b5b66",
        mint: "#20da84",
        gold: "#ffd34e",
        danger: "#c64d4d",
        line: "rgba(22, 60, 63, 0.08)"
      },
      fontFamily: {
        display: ['"Manrope"', "sans-serif"],
        mono: ['"IBM Plex Mono"', "monospace"]
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(11, 91, 102, 0.14), 0 18px 60px rgba(24, 44, 47, 0.18)"
      },
      backgroundImage: {
        shell: "radial-gradient(circle at top left, rgba(255, 255, 255, 0.05), transparent 18%), linear-gradient(180deg, #2f5659 0%, #234649 100%)"
      }
    }
  },
  plugins: []
};

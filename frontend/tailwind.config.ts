import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#182026",
        paper: "#f7f7f2",
        signal: "#1f8a70",
        caution: "#d18a22",
        danger: "#b64040",
      },
      boxShadow: {
        panel: "0 10px 30px rgba(24, 32, 38, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;

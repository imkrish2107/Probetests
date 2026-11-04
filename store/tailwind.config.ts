import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F4F0E8",
        ink: "#1C1A17",
        oxblood: "#6E1F1B",
      },
      fontFamily: {
        display: ['"Newsreader"', "Georgia", "serif"],
        body: ['"Familjen Grotesk"', "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;

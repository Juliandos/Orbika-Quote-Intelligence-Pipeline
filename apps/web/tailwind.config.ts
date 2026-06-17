import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#20232d",
        mist: "#eef1ec",
        clay: "#c7ccc2",
        olive: "#58654d",
        pine: "#2f4334",
        sand: "#e9e4d8",
        ember: "#8a5b4f",
      },
      boxShadow: {
        panel: "0 12px 35px rgba(32, 35, 45, 0.08)",
      },
      borderRadius: {
        xl: "1rem",
      },
    },
  },
  plugins: [],
};

export default config;

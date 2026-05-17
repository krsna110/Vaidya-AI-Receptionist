import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      borderRadius: {
        '2xl': '1rem'
      },
      colors: {
        bg: "#050a15",
        panel: "#0b1327",
        cyan: "#2dd4bf",
        glow: "#60a5fa"
      },
      backgroundImage: {
        'soft-medical': 'radial-gradient(circle at 10% 10%, rgba(59,130,246,0.2), transparent 35%), radial-gradient(circle at 90% 20%, rgba(45,212,191,0.18), transparent 35%), linear-gradient(180deg, #050a15, #060f1f)'
      },
      boxShadow: {
        glass: '0 10px 30px rgba(7, 16, 35, 0.45)'
      }
    }
  },
  plugins: []
};

export default config;

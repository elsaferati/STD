import forms from "@tailwindcss/forms";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        primary: "#3b82f6",
        "primary-dark": "#2563eb",
        "background-light": "#f6f8f8",
        "background-dark": "#102022",
        "surface-light": "#ffffff",
        "surface-dark": "#162a2d",
        success: "#10b981",
        warning: "#f59e0b",
        danger: "#ef4444",
      },
      fontFamily: {
        display: ["Space Grotesk", "sans-serif"],
        login: ["IBM Plex Sans", "Space Grotesk", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 20px -5px rgba(59, 130, 246, 0.28)",
      },
    },
  },
  plugins: [forms],
};

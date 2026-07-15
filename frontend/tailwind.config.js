/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: '#080C14',
          panel: '#111827',
          border: '#2A3A52',
          green: '#5EE9A6',
          red: '#FF718A',
          yellow: '#F6C85F',
          cyan: '#65D9F3',
          muted: '#9AA9BF',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: '#0a0e14',
          panel: '#111820',
          border: '#1e2a3a',
          green: '#00ff88',
          red: '#ff4466',
          yellow: '#ffd166',
          cyan: '#4dd0e1',
          muted: '#6b7c93',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}

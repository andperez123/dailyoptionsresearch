/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        research: {
          bg: '#F4F6F4',
          surface: '#FFFFFF',
          ink: '#0B1410',
          muted: '#5C6B62',
          line: '#E3E8E4',
          green: '#00C805',
          'green-soft': '#E8F9E9',
          red: '#F45531',
          'red-soft': '#FDECE8',
          amber: '#C47F17',
          'amber-soft': '#FBF3E4',
          blue: '#1A6BFF',
          'blue-soft': '#EAF0FF',
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        soft: '0 1px 2px rgb(11 20 16 / 0.04), 0 8px 24px rgb(11 20 16 / 0.04)',
        sheet: '0 16px 48px rgb(11 20 16 / 0.12)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in': {
          from: { opacity: '0', transform: 'translateX(16px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 280ms ease-out',
        'slide-in': 'slide-in 280ms ease-out',
      },
    },
  },
  plugins: [],
}

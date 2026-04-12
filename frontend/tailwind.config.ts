import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas:      '#191626',
        panel:       '#332042',
        panelBorder: '#7a5a89',
        lavender:    '#ae7db7',
        success:     '#4fc329',
        danger:      '#e35658',
      },
      fontFamily: {
        display: ['"Bree Serif"', 'serif'],
        body:    ['Lexend', 'sans-serif'],
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(185,135,199,0.35), 0 12px 40px rgba(13,10,22,0.6)',
      },
    },
  },
  plugins: [],
} satisfies Config

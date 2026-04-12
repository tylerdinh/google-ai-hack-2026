import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: '#1a1714',
          mid:     '#2e2a26',
          soft:    '#3d3832',
        },
        stone: {
          DEFAULT: '#7a7068',
          mid:     '#5a5248',
        },
        mist:      '#b8afa6',
        fog:       '#d8d2cc',
        parchment: '#f0ece8',
        cream:     '#f9f7f5',
        accent: {
          DEFAULT: '#8b7355',
          lit:     '#a8906d',
          dim:     '#6b5840',
        },
        ok:        '#4a7c59',
        no:        '#8b3a3c',
      },
      fontFamily: {
        display: ['"Cormorant Garamond"', 'Georgia', 'serif'],
        body:    ['"DM Sans"', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        sm:  '6px',
        DEFAULT: '12px',
        lg:  '18px',
        xl:  '24px',
        full: '9999px',
      },
      boxShadow: {
        sm:  '0 1px 3px rgba(26,23,20,0.08)',
        DEFAULT: '0 4px 16px rgba(26,23,20,0.10), 0 1px 3px rgba(26,23,20,0.06)',
        lg:  '0 8px 32px rgba(26,23,20,0.12), 0 2px 8px rgba(26,23,20,0.06)',
        xl:  '0 16px 48px rgba(26,23,20,0.14), 0 4px 12px rgba(26,23,20,0.08)',
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '1rem' }],
        xs:    ['0.72rem',  { lineHeight: '1.1rem' }],
        sm:    ['0.8rem',   { lineHeight: '1.25rem' }],
        base:  ['0.88rem',  { lineHeight: '1.5rem' }],
        lg:    ['1rem',     { lineHeight: '1.6rem' }],
        xl:    ['1.15rem',  { lineHeight: '1.7rem' }],
        '2xl': ['1.4rem',   { lineHeight: '1.3' }],
        '3xl': ['1.8rem',   { lineHeight: '1.2' }],
        '4xl': ['2.4rem',   { lineHeight: '1.1' }],
        '5xl': ['3rem',     { lineHeight: '1' }],
      },
      spacing: {
        '4.5':  '1.125rem',
        '13':   '3.25rem',
        '15':   '3.75rem',
        '18':   '4.5rem',
        '22':   '5.5rem',
        '26':   '6.5rem',
      },
      animation: {
        'fade-up':  'fadeUp 0.32s cubic-bezier(0.22,1,0.36,1) forwards',
        'fade-in':  'fadeIn 0.24s ease forwards',
        'spin-slow':'spin 0.9s linear infinite',
        'pulse-slow':'pulse 1.6s ease-in-out infinite',
        'shimmer':  'skeleton-shimmer 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config
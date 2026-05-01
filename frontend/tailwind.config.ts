import type { Config } from 'tailwindcss';

export default {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Cool light-grey theme — close to macOS Safari Home palette
        // (revised 2026-04-30 to replace the warmer beige scheme).
        bg: '#fbfbfc',
        'bg-deep': '#e6e7ea',
        'bg-surface': '#ffffff',
        'bg-surface2': '#f1f2f5',

        line: '#e3e4e8',
        'line-strong': '#d6d7dc',

        ink: '#1d1d1f',
        'ink-2': '#5b5d63',
        'ink-3': '#8a8b91',

        // Direction-aware account-label colours (used in transfer pair rows).
        'acc-in':  '#1d4f8a',
        'acc-out': '#c47700',

        'accent-green': '#14613b',
        'accent-green-soft': '#e6f1ea',
        'accent-amber': '#8a5a00',
        'accent-amber-soft': '#fbf0d8',
        'accent-red': '#8b1f1f',
        'accent-red-soft': '#f6e3e0',
        'accent-blue': '#1d4f8a',
        'accent-blue-soft': '#e3edf8',
        'accent-violet': '#5b3a8a',
        'accent-violet-soft': '#ece2f6',

        // Traffic-light buttons (excl/snooze/apply).
        'traffic-green': '#1e8a4f',
        'traffic-amber': '#d49b1a',
        'traffic-red':   '#e54033',

        // Legacy semantic — kept so slate-based screens still compile
        // until they're individually migrated.
        border: '#e3e4e8',
        background: '#fbfbfc',
        foreground: '#1d1d1f',
        muted: '#8a8b91',
        primary: '#1d1d1f',
        card: '#ffffff',
        danger: '#8b1f1f',
      },
      fontFamily: {
        // Loaded via Google Fonts CDN in app/layout.tsx (matches the mockup).
        sans:  ['Geist', '-apple-system', 'system-ui', 'sans-serif'],
        serif: ['"Instrument Serif"', 'Georgia', 'serif'],
        mono:  ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        soft: '0 10px 30px rgba(15, 23, 42, 0.08)',
        pill: '0 2px 6px rgba(0, 0, 0, 0.04)',
        pillHover: '0 4px 14px rgba(0, 0, 0, 0.06)',
        modal: '0 30px 80px rgba(0, 0, 0, 0.25), 0 6px 18px rgba(0, 0, 0, 0.08)',
        fab: '0 6px 18px rgba(0, 0, 0, 0.18), 0 1px 3px rgba(0, 0, 0, 0.08)',
        fabActive: '0 10px 28px rgba(0, 0, 0, 0.22), 0 2px 6px rgba(0, 0, 0, 0.1)',
      },
      borderRadius: {
        '2xl': '0.875rem', // 14px
        '3xl': '1rem',     // 16px (cards)
        pill: '9999px',
      },
      keyframes: {
        razvorotIn: {
          '0%': { opacity: '0', transform: 'scale(0.05)' },
          '60%': { opacity: '1' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        selectIn: {
          from: { opacity: '0', transform: 'translateY(-4px)' },
          to: { opacity: '1', transform: 'none' },
        },
        expandRow: {
          from: { opacity: '0', maxHeight: '0' },
          to: { opacity: '1', maxHeight: '1200px' },
        },
      },
      animation: {
        razvorot: 'razvorotIn 0.32s cubic-bezier(0.16, 0.84, 0.3, 1) forwards',
        fadeIn: 'fadeIn 0.18s ease-out',
        selectIn: 'selectIn 0.12s ease-out',
        expandRow: 'expandRow 0.26s ease-out',
      },
    },
  },
  plugins: [
    // Container queries — позволяет виджетам реагировать на ширину родителя,
    // а не на ширину окна. Например, KPI-карточки внутри сайдбара 280px
    // могут автоматически переключаться на 1 колонку, а в основной зоне
    // 1600px — на 4 колонки одновременно. Применяется через `@container`
    // на родителе и `@md:`, `@lg:`, `@xl:` префиксы на потомках.
    require('@tailwindcss/container-queries'),
  ],
} satisfies Config;

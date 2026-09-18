import type { Config } from 'tailwindcss';

/**
 * The Exhibit Record — token bridge.
 *
 * Tailwind never owns a literal colour here. Every value resolves to a CSS custom
 * property declared in `globals.css`, so a theme change is a `:root` change and
 * nothing in component code has to know which theme is active.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        board: 'var(--board)',
        'board-sunk': 'var(--board-sunk)',
        leaf: 'var(--leaf)',
        'leaf-raised': 'var(--leaf-raised)',
        overlay: 'var(--overlay)',
        scrim: 'var(--scrim)',
        rule: 'var(--rule)',
        'rule-strong': 'var(--rule-strong)',
        ink: 'var(--ink-0)',
        'ink-1': 'var(--ink-1)',
        'ink-2': 'var(--ink-2)',
        'ink-3': 'var(--ink-3)',
        'ink-inverse': 'var(--ink-inverse)',
        stamp: 'var(--stamp)',
        'stamp-weak': 'var(--stamp-weak)',
        seal: 'var(--seal)',
        'seal-weak': 'var(--seal-weak)',
        caution: 'var(--caution)',
        'caution-weak': 'var(--caution-weak)',
        held: 'var(--held)',
        'held-weak': 'var(--held-weak)',
        focus: 'var(--focus)',
        'mod-document': 'var(--mod-document)',
        'mod-image': 'var(--mod-image)',
        'mod-video': 'var(--mod-video)',
        'mod-audio': 'var(--mod-audio)',
        'mod-database': 'var(--mod-database)',
        'mod-graph': 'var(--mod-graph)',
        'mod-external': 'var(--mod-external)',
      },
      fontFamily: {
        sans: 'var(--font-sans)',
        mono: 'var(--font-mono)',
      },
      fontSize: {
        micro: ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.06em' }],
        mark: ['0.75rem', { lineHeight: '1.125rem', letterSpacing: '0.01em' }],
        body: ['0.8125rem', { lineHeight: '1.3125rem' }],
        prose: ['0.9375rem', { lineHeight: '1.55rem' }],
        head: ['1.0625rem', { lineHeight: '1.4rem', letterSpacing: '-0.011em' }],
        title: ['1.375rem', { lineHeight: '1.65rem', letterSpacing: '-0.018em' }],
        display: ['2rem', { lineHeight: '2.25rem', letterSpacing: '-0.026em' }],
      },
      borderRadius: {
        none: '0',
        sm: '2px',
        DEFAULT: '3px',
        md: '4px',
        lg: '6px',
      },
      boxShadow: {
        leaf: 'var(--shadow-leaf)',
        overlay: 'var(--shadow-overlay)',
      },
      spacing: {
        rail: 'var(--rail-w)',
        header: 'var(--header-h)',
      },
      transitionTimingFunction: {
        step: 'cubic-bezier(0.2, 0.9, 0.25, 1)',
      },
      keyframes: {
        'leaf-in': {
          from: { opacity: '0', transform: 'translateY(3px)' },
          to: { opacity: '1', transform: 'none' },
        },
        'overlay-in': {
          from: { opacity: '0', transform: 'translateY(8px) scale(0.995)' },
          to: { opacity: '1', transform: 'none' },
        },
        'scrim-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'rule-sweep': {
          '0%': { transform: 'scaleX(0)', transformOrigin: 'left' },
          '50%': { transform: 'scaleX(1)', transformOrigin: 'left' },
          '50.001%': { transform: 'scaleX(1)', transformOrigin: 'right' },
          '100%': { transform: 'scaleX(0)', transformOrigin: 'right' },
        },
      },
      animation: {
        'leaf-in': 'leaf-in 160ms cubic-bezier(0.2, 0.9, 0.25, 1) both',
        'overlay-in': 'overlay-in 190ms cubic-bezier(0.2, 0.9, 0.25, 1) both',
        'scrim-in': 'scrim-in 140ms linear both',
        'rule-sweep': 'rule-sweep 1500ms cubic-bezier(0.65, 0, 0.35, 1) infinite',
      },
    },
  },
  plugins: [],
};

export default config;

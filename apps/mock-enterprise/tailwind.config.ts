import type { Config } from 'tailwindcss';

/**
 * Deliberately plain, utilitarian palette: this is an internal
 * line-of-business system, not the SPECTRA console.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Segoe UI', 'Helvetica Neue', 'Arial', 'system-ui', 'sans-serif'],
        mono: ['Consolas', 'Menlo', 'Monaco', 'monospace'],
      },
      colors: {
        ink: {
          DEFAULT: '#1a1d21',
          muted: '#4a5057',
          faint: '#6b7280',
        },
        line: '#c9ced6',
        surface: '#f4f5f7',
        chrome: '#25303c',
      },
      fontSize: {
        xxs: ['0.6875rem', '1rem'],
      },
    },
  },
  plugins: [],
};

export default config;

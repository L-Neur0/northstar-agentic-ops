/**
 * Tailwind configuration (spec 10 §3.3; spec 23 §3.13.1, §3.13.2; AC-23.57).
 * Why: the app has a light and a dark theme switched by the `dark` class on <html>, and every
 * colour is a token from src/index.css, so components never need two colour classes.
 * What: darkMode "class", and colour names mapped to the CSS variables in rgb(... / <alpha-value>)
 * form so opacity utilities work. Scans index.html and src/.
 * Must not: add raw palette colours for components; a new colour is a new token in index.css.
 */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}', '!./src/**/*.test.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        page: token('bg'),
        surface: { DEFAULT: token('surface'), muted: token('surface-muted'), strong: token('surface-strong') },
        line: { DEFAULT: token('border'), strong: token('border-strong') },
        fg: token('text'),
        muted: token('text-muted'),
        subtle: token('text-subtle'),
        link: token('link'),
        primary: { DEFAULT: token('primary'), hover: token('primary-hover'), contrast: token('primary-contrast'), soft: token('primary-soft') },
        success: { DEFAULT: token('success'), soft: token('success-soft') },
        warning: { DEFAULT: token('warning'), soft: token('warning-soft') },
        danger: {
          DEFAULT: token('danger'),
          soft: token('danger-soft'),
          solid: token('danger-solid'),
          'solid-hover': token('danger-solid-hover'),
        },
        bubble: { expert: token('bubble-expert'), agent: token('bubble-agent') },
        overlay: token('overlay'),
      },
    },
  },
  plugins: [],
}

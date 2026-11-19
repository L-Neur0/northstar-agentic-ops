/** PostCSS pipeline for Tailwind (spec 10 §3.3). Tailwind generates the utility classes; autoprefixer adds vendor prefixes. Nothing else runs here. */
export default { plugins: { tailwindcss: {}, autoprefixer: {} } }

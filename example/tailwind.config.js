// tailwind.config.js
// Integração Material Tailwind HTML + Django.
// O arquivo gerado é compilado para `static/css/tailwind.css` e consumido pelo {% compress %}.

const withMT = require("@material-tailwind/html/utils/withMT");

module.exports = withMT({
  content: [
    "./templates/**/*.html",
    "./**/templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Manrope', 'ui-sans-serif', 'system-ui'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        ink: {
          50:  '#f6f7f9', 100: '#eceef2', 200: '#dde0e6', 300: '#c2c7d0',
          400: '#8a92a0', 500: '#5d6675', 600: '#414957', 700: '#2d343f',
          800: '#1c2230', 900: '#0f1422',
        },
        brand: {
          50:  '#eef4ff', 100: '#dbe6ff', 200: '#b7cdff', 300: '#85adff',
          400: '#5687ff', 500: '#2f63f6', 600: '#1f4ee0', 700: '#1a3eb8',
          800: '#1a3590', 900: '#1a2e74',
        },
        ok:   { 50:'#ecfdf5', 100:'#d1fae5', 500:'#10b981', 600:'#059669', 700:'#047857' },
        warn: { 50:'#fff8eb', 100:'#fef0c7', 500:'#f59e0b', 600:'#d97706', 700:'#b45309' },
        err:  { 50:'#fef2f2', 100:'#fee2e2', 500:'#ef4444', 600:'#dc2626', 700:'#b91c1c' },
      },
      boxShadow: {
        card: '0 1px 2px rgba(15,20,34,.04), 0 1px 1px rgba(15,20,34,.03)',
        pop:  '0 8px 24px rgba(15,20,34,.08), 0 2px 6px rgba(15,20,34,.05)',
      },
    },
  },
  plugins: [],
});
